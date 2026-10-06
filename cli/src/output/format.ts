import type { UploadError } from '../errors/UploadError.js';
import type { Result } from '../types.js';
import type { UploadSuccess } from '../upload/httpClient.js';

export interface FormattedOutput {
  stdout?: string;
  stderr?: string;
  exitCode: 0 | 1;
}

/**
 * Pure: turns a result (success w/ run URL, or a typed error) into the
 * exact stdout/stderr strings from the spec's error-copy, and the
 * corresponding exit code. Isolated so copy changes don't touch logic, and
 * so tests can assert on message text without mocking I/O.
 */
export function formatResult(result: Result<UploadSuccess, UploadError>): FormattedOutput {
  if (result.ok) {
    return {
      stdout: `tracewell upload: run recorded — ${result.value.runUrl}`,
      exitCode: 0,
    };
  }

  return {
    stderr: formatError(result.error),
    exitCode: 1,
  };
}

function formatError(error: UploadError): string {
  switch (error.kind) {
    case 'Auth':
      return `tracewell upload: authentication failed — the API token was rejected (${error.status}). Check TRACEWELL_API_TOKEN and try again.`;
    case 'Network':
      return `tracewell upload: could not reach ${error.apiUrl} after ${error.attempts} attempts — check network access and the configured --api-url.`;
    case 'ReportNotFound':
      return `tracewell upload: no report file found at ${error.path} — run Playwright with the json reporter first, or pass --report-file.`;
    case 'MalformedReport':
      return `tracewell upload: malformed report at ${error.path || '(report)'} — ${error.reason}`;
    case 'MalformedConfig':
      return `tracewell upload: malformed config file at ${error.path} — ${error.reason}`;
    case 'Server':
      return `tracewell upload: server error (${error.status}) after ${error.attempts} attempt(s) — the upload was not recorded.`;
  }
}
