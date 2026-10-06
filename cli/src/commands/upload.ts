import path from 'node:path';
import { resolveConfig, type ParsedFlags } from '../config/resolveConfig.js';
import { loadConfigFile } from '../config/loadConfigFile.js';
import { locateReport } from '../report/locateReport.js';
import { parseReport } from '../report/parseReport.js';
import { resolveAttachments } from '../report/resolveAttachments.js';
import { buildMultipartRequest } from '../upload/buildMultipartRequest.js';
import { uploadWithRetry } from '../upload/httpClient.js';
import { formatResult, type FormattedOutput } from '../output/format.js';
import { err } from '../types.js';
import { readFileSync } from 'node:fs';

export interface RunUploadInput {
  cwd: string;
  flags: ParsedFlags;
  env: Record<string, string | undefined>;
}

/**
 * Orchestration layer for the `upload` subcommand: wires config resolution
 * → report parsing → attachment resolution → HTTP upload → output
 * formatting. The only module permitted to sequence multiple other
 * modules' calls.
 */
export async function runUpload(input: RunUploadInput): Promise<FormattedOutput> {
  const loadedConfigFile = loadConfigFile(input.cwd);
  if (!loadedConfigFile.ok) {
    return formatResult(err(loadedConfigFile.error));
  }
  const config = resolveConfig(input.flags, input.env, loadedConfigFile.value);

  const located = locateReport(config.reportFile, input.cwd);
  if (!located.ok) {
    return formatResult(err(located.error));
  }

  const raw = readFileSync(located.value, 'utf-8');
  const parsed = parseReport(raw);
  if (!parsed.ok) {
    return formatResult(err({ ...parsed.error, path: located.value }));
  }

  const reportDir = path.dirname(located.value);
  const { resolved } = resolveAttachments(parsed.value, reportDir);

  const spec = buildMultipartRequest(parsed.value, resolved, config.projectId);

  const uploadResult = await uploadWithRetry(spec, {
    apiUrl: config.apiUrl,
    reportFile: config.reportFile,
    ...(config.token !== undefined ? { token: config.token } : {}),
  });

  return formatResult(uploadResult);
}
