/**
 * Shared types used across module boundaries.
 *
 * `Result<T, E>` is used throughout instead of throwing for *expected*
 * failure modes (bad report, auth failure, network failure). Thrown
 * exceptions are reserved for genuine programmer errors.
 */
export type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };

export function ok<T>(value: T): { ok: true; value: T } {
  return { ok: true, value };
}

export function err<E>(error: E): { ok: false; error: E } {
  return { ok: false, error };
}

/** One attachment reference as it appears in a Playwright JSON report entry. */
export interface AttachmentRef {
  name: string;
  path?: string;
  contentType: string;
}

export type TestOutcome = 'passed' | 'failed' | 'skipped' | 'flaky';

export interface RetryAttempt {
  status: 'passed' | 'failed' | 'timedOut' | 'skipped' | 'interrupted';
  duration: number;
  attachments: AttachmentRef[];
}

export interface ParsedTest {
  id: string;
  title: string;
  outcome: TestOutcome;
  retries: RetryAttempt[];
  attachments: AttachmentRef[];
}

export interface ParsedRun {
  tests: ParsedTest[];
}
