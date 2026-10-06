import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { parseReport } from '../../src/report/parseReport.js';

const fixturesDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'fixtures');

function readFixture(name: string): string {
  return readFileSync(path.join(fixturesDir, name), 'utf-8');
}

describe('parseReport', () => {
  it('parses a valid all-pass report into tests with outcomes and attachments', () => {
    const raw = readFixture('all-pass.json');

    const result = parseReport(raw);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.tests).toHaveLength(2);
    expect(result.value.tests[0]).toMatchObject({
      title: 'renders the homepage',
      outcome: 'passed',
    });
    expect(result.value.tests[0]?.attachments).toEqual([
      { name: 'screenshot', path: 'data/homepage.png', contentType: 'image/png' },
    ]);
    expect(result.value.tests[1]).toMatchObject({
      title: 'renders the login page',
      outcome: 'passed',
    });
  });

  it('parses an empty report (zero tests ran) as a run with zero tests, not an error', () => {
    const raw = readFixture('empty-run.json');

    const result = parseReport(raw);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.tests).toEqual([]);
  });

  it('returns a MalformedReportError for invalid JSON instead of throwing', () => {
    const raw = '{ this is not valid json ';

    const result = parseReport(raw);

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe('MalformedReport');
  });

  it('returns a MalformedReportError when the top-level "suites" array is missing', () => {
    const raw = JSON.stringify({ notSuites: [] });

    const result = parseReport(raw);

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe('MalformedReport');
  });

  it('classifies a test that fails on every attempt as "failed"', () => {
    const raw = readFixture('all-fail.json');

    const result = parseReport(raw);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.tests).toHaveLength(1);
    expect(result.value.tests[0]?.outcome).toBe('failed');
    expect(result.value.tests[0]?.retries).toHaveLength(1);
  });

  it('preserves full retry history for a test that eventually passes, not just the final attempt', () => {
    const raw = readFixture('with-retries.json');

    const result = parseReport(raw);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.tests).toHaveLength(1);
    const test = result.value.tests[0];
    expect(test?.outcome).toBe('flaky');
    expect(test?.retries).toHaveLength(3);
    expect(test?.retries.map((r) => r.status)).toEqual(['failed', 'failed', 'passed']);
  });
});
