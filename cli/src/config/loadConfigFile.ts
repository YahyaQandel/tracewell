import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import type { MalformedConfigError } from '../errors/UploadError.js';
import { err, ok, type Result } from '../types.js';

/**
 * Non-secret values a team wants committed rather than repeated as flags.
 * The token is deliberately excluded from this shape — secrets don't belong
 * in a committed config file, so `loadConfigFile` never reads a `token`
 * field even if one is present in the file on disk.
 */
export interface ConfigFile {
  projectId?: string;
  apiUrl?: string;
  reportFile?: string;
}

const CONFIG_FILE_NAMES = ['tracewell.config.json', '.tracewellrc.json'];

/**
 * I/O-only: finds and reads a config file from `cwd`. Returns parsed JSON
 * (with any `token` field stripped), `undefined` if no config file is
 * present, or a typed `MalformedConfigError` if the file exists but is not
 * valid JSON — never throws (GitHub issue #4: an unguarded JSON.parse here
 * used to crash the whole CLI with a raw SyntaxError instead of flowing
 * through the same typed-error/formatResult pipeline every other failure
 * mode uses). Search is CWD-only for this ticket (see design.md Risks —
 * upward-to-repo-root search is a later enhancement, not required here).
 */
export function loadConfigFile(cwd: string): Result<ConfigFile | undefined, MalformedConfigError> {
  for (const fileName of CONFIG_FILE_NAMES) {
    const candidate = path.join(cwd, fileName);
    if (existsSync(candidate)) {
      const raw = readFileSync(candidate, 'utf-8');
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(raw) as Record<string, unknown>;
      } catch (e) {
        return err({
          kind: 'MalformedConfig',
          path: candidate,
          reason: e instanceof Error ? e.message : 'invalid JSON',
        });
      }
      const { projectId, apiUrl, reportFile } = parsed;
      return ok({
        ...(typeof projectId === 'string' ? { projectId } : {}),
        ...(typeof apiUrl === 'string' ? { apiUrl } : {}),
        ...(typeof reportFile === 'string' ? { reportFile } : {}),
      });
    }
  }
  return ok(undefined);
}
