import type { ConfigFile } from './loadConfigFile.js';

export interface ParsedFlags {
  projectId?: string;
  apiUrl?: string;
  reportFile?: string;
  token?: string;
}

export interface ResolvedConfig {
  projectId?: string;
  apiUrl: string;
  reportFile: string;
  token?: string;
}

const DEFAULT_API_URL = 'https://api.tracewell.dev';
const DEFAULT_REPORT_FILE = 'playwright-report/results.json';

/**
 * Pure function over already-loaded inputs: resolves `projectId`, `apiUrl`,
 * `reportFile`, `token` from flags/env/config-file/defaults per precedence
 * CLI flag > environment variable > config file > built-in default.
 *
 * The token is never read from the config file by design — `ConfigFile`'s
 * type has no `token` field, so a config file literally cannot supply one
 * here, only `flags.token` or `env.TRACEWELL_API_TOKEN` can.
 */
export function resolveConfig(
  flags: ParsedFlags,
  env: Record<string, string | undefined>,
  configFile: ConfigFile | undefined,
): ResolvedConfig {
  const projectId = flags.projectId ?? env.TRACEWELL_PROJECT_ID ?? configFile?.projectId ?? undefined;

  const apiUrl =
    flags.apiUrl ?? env.TRACEWELL_API_URL ?? configFile?.apiUrl ?? DEFAULT_API_URL;

  const reportFile =
    flags.reportFile ?? env.TRACEWELL_REPORT_FILE ?? configFile?.reportFile ?? DEFAULT_REPORT_FILE;

  const token = flags.token ?? env.TRACEWELL_API_TOKEN ?? undefined;

  return {
    ...(projectId !== undefined ? { projectId } : {}),
    apiUrl,
    reportFile,
    ...(token !== undefined ? { token } : {}),
  };
}
