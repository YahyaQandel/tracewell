import { describe, expect, it } from 'vitest';
import { formatResult } from '../../src/output/format.js';
import { ok, err } from '../../src/types.js';

describe('formatResult', () => {
  it('formats a success result as a confirmation link on stdout with exit code 0', () => {
    const result = ok({ runId: 'run-123', runUrl: 'https://tracewell.dev/runs/run-123' });

    const formatted = formatResult(result);

    expect(formatted.exitCode).toBe(0);
    expect(formatted.stdout).toContain('https://tracewell.dev/runs/run-123');
    expect(formatted.stderr).toBeUndefined();
  });

  it('formats an AuthError with the exact spec copy and exit code 1', () => {
    const result = err({ kind: 'Auth' as const, status: 401 as const });

    const formatted = formatResult(result);

    expect(formatted.exitCode).toBe(1);
    expect(formatted.stderr).toBe(
      'tracewell upload: authentication failed — the API token was rejected (401). Check TRACEWELL_API_TOKEN and try again.',
    );
  });

  it('formats a NetworkError with the exact spec copy, including the api-url, and exit code 1', () => {
    const result = err({
      kind: 'Network' as const,
      apiUrl: 'https://api.tracewell.dev',
      attempts: 3,
      cause: 'ECONNREFUSED',
    });

    const formatted = formatResult(result);

    expect(formatted.exitCode).toBe(1);
    expect(formatted.stderr).toBe(
      'tracewell upload: could not reach https://api.tracewell.dev after 3 attempts — check network access and the configured --api-url.',
    );
  });

  it('formats a ReportNotFoundError with the exact spec copy, including the path, and exit code 1', () => {
    const result = err({
      kind: 'ReportNotFound' as const,
      path: '/repo/playwright-report/results.json',
    });

    const formatted = formatResult(result);

    expect(formatted.exitCode).toBe(1);
    expect(formatted.stderr).toBe(
      'tracewell upload: no report file found at /repo/playwright-report/results.json — run Playwright with the json reporter first, or pass --report-file.',
    );
  });

  it('formats a MalformedReportError with exit code 1 (surfaced, not retried)', () => {
    const result = err({
      kind: 'MalformedReport' as const,
      path: '/repo/playwright-report/results.json',
      reason: 'unexpected token',
    });

    const formatted = formatResult(result);

    expect(formatted.exitCode).toBe(1);
    expect(formatted.stderr).toContain('malformed');
  });

  it('formats a ServerError with exit code 1, surfacing the server status verbatim', () => {
    const result = err({
      kind: 'Server' as const,
      status: 503,
      attempts: 3,
    });

    const formatted = formatResult(result);

    expect(formatted.exitCode).toBe(1);
    expect(formatted.stderr).toContain('503');
  });
});
