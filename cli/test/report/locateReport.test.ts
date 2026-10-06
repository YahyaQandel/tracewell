import { describe, expect, it, afterEach } from 'vitest';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { locateReport } from '../../src/report/locateReport.js';

describe('locateReport', () => {
  let dir: string;

  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true });
  });

  it('returns the absolute path when the report file exists', () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-test-'));
    const reportPath = path.join(dir, 'results.json');
    writeFileSync(reportPath, '{}');

    const result = locateReport('results.json', dir);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value).toBe(reportPath);
  });

  it('returns a ReportNotFoundError naming the resolved path when the file does not exist', () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-test-'));

    const result = locateReport('playwright-report/results.json', dir);

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe('ReportNotFound');
    expect(result.error.path).toBe(path.join(dir, 'playwright-report/results.json'));
  });

  it('accepts an already-absolute report path as-is', () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-test-'));
    const reportPath = path.join(dir, 'custom-results.json');
    writeFileSync(reportPath, '{}');

    const result = locateReport(reportPath, '/some/unrelated/cwd');

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value).toBe(reportPath);
  });
});
