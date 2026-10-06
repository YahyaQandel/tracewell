/**
 * Typed error hierarchy for the upload pipeline. Errors are discriminated
 * unions keyed on `kind`, never string-matched against a caught exception's
 * `.message`. This keeps the spec's exact error copy in exactly one place
 * (src/output/format.ts) instead of scattered across catch blocks.
 */

export interface ReportNotFoundError {
  kind: 'ReportNotFound';
  path: string;
}

export interface MalformedReportError {
  kind: 'MalformedReport';
  path: string;
  reason: string;
}

/**
 * A `tracewell.config.json` / `.tracewellrc.json` file was found but could
 * not be parsed as JSON. Distinct from MalformedReportError (that's the
 * Playwright report file, this is the CLI's own config file) so the error
 * copy and any future handling can differ without string-matching a path.
 */
export interface MalformedConfigError {
  kind: 'MalformedConfig';
  path: string;
  reason: string;
}

export interface AuthError {
  kind: 'Auth';
  status: 401 | 403;
}

export interface NetworkError {
  kind: 'Network';
  apiUrl: string;
  attempts: number;
  cause: string;
}

export interface ServerError {
  kind: 'Server';
  status: number;
  attempts: number;
  body?: string;
}

export type UploadError =
  | ReportNotFoundError
  | MalformedReportError
  | MalformedConfigError
  | AuthError
  | NetworkError
  | ServerError;
