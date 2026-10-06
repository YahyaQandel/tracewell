import { existsSync } from 'node:fs';
import path from 'node:path';
import type { ReportNotFoundError } from '../errors/UploadError.js';
import { err, ok, type Result } from '../types.js';

/**
 * I/O: resolves the report file path to an absolute path and checks
 * existence. Returns a typed result, not a thrown string.
 */
export function locateReport(reportFileArg: string, cwd: string): Result<string, ReportNotFoundError> {
  const absolutePath = path.isAbsolute(reportFileArg)
    ? reportFileArg
    : path.resolve(cwd, reportFileArg);

  if (!existsSync(absolutePath)) {
    return err({ kind: 'ReportNotFound', path: absolutePath });
  }

  return ok(absolutePath);
}
