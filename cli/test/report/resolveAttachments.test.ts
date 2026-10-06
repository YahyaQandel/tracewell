import { describe, expect, it, vi, afterEach } from 'vitest';
import { mkdtempSync, writeFileSync, readFileSync, rmSync, mkdirSync, renameSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { resolveAttachments } from '../../src/report/resolveAttachments.js';
import { parseReport } from '../../src/report/parseReport.js';
import type { ParsedRun } from '../../src/types.js';

const fixturesDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'fixtures');

function makeRun(attachments: { name: string; path?: string; contentType: string }[]): ParsedRun {
  return {
    tests: [
      {
        id: 'renders the homepage',
        title: 'renders the homepage',
        outcome: 'passed',
        retries: [{ status: 'passed', duration: 10, attachments }],
        attachments,
      },
    ],
  };
}

describe('resolveAttachments', () => {
  let dir: string;

  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true });
  });

  it('resolves all attachments when every referenced file is present on disk', () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-test-'));
    writeFileSync(path.join(dir, 'homepage.png'), 'fake-png-bytes');

    const run = makeRun([{ name: 'screenshot', path: 'homepage.png', contentType: 'image/png' }]);

    const result = resolveAttachments(run, dir);

    expect(result.resolved).toHaveLength(1);
    expect(result.missing).toHaveLength(0);
    expect(result.resolved[0]).toMatchObject({
      name: 'screenshot',
      contentType: 'image/png',
      absolutePath: path.join(dir, 'homepage.png'),
    });
  });

  it('reports a missing attachment and continues, warning instead of failing the whole run', () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-test-'));
    // Intentionally do not create the file on disk.
    const warnSpy = vi.fn();

    const run = makeRun([
      { name: 'trace', path: 'does-not-exist-trace.zip', contentType: 'application/zip' },
    ]);

    const result = resolveAttachments(run, dir, { onMissing: warnSpy });

    expect(result.resolved).toHaveLength(0);
    expect(result.missing).toHaveLength(1);
    expect(result.missing[0]).toMatchObject({ name: 'trace' });
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0]?.[0]).toMatch(/does-not-exist-trace\.zip/);
  });

  it('resolves present attachments and reports missing ones in the same run, without failing it', () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-test-'));
    writeFileSync(path.join(dir, 'present.png'), 'bytes');

    const run = makeRun([
      { name: 'screenshot', path: 'present.png', contentType: 'image/png' },
      { name: 'trace', path: 'missing.zip', contentType: 'application/zip' },
    ]);

    const result = resolveAttachments(run, dir);

    expect(result.resolved).toHaveLength(1);
    expect(result.missing).toHaveLength(1);
  });

  it('using the with-missing-attachment fixture: resolves the present screenshot and warns on the missing trace, without failing the run', () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-test-'));
    writeFileSync(path.join(dir, 'homepage.png'), 'fake-png-bytes');
    // Deliberately do not create does-not-exist-trace.zip — the fixture
    // references it to model a missing attachment.

    const raw = readFileSync(path.join(fixturesDir, 'with-missing-attachment.json'), 'utf-8');
    const parsed = parseReport(raw);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;

    // Fixture paths are written relative to "data/", rewrite reportDir
    // accordingly so this test models the real relative-path resolution.
    const dataDir = path.join(dir, 'data');
    mkdirSync(dataDir, { recursive: true });
    renameSync(path.join(dir, 'homepage.png'), path.join(dataDir, 'homepage.png'));

    const warnSpy = vi.fn();
    const result = resolveAttachments(parsed.value, dir, { onMissing: warnSpy });

    expect(result.resolved).toHaveLength(1);
    expect(result.resolved[0]).toMatchObject({ name: 'screenshot' });
    expect(result.missing).toHaveLength(1);
    expect(result.missing[0]).toMatchObject({ name: 'trace' });
    expect(warnSpy).toHaveBeenCalledTimes(1);
  });

  // Regression test for GitHub issue #6: attachments from any retry attempt
  // except the LAST were silently dropped. Root cause: parseReport only
  // populated the top-level ParsedTest.attachments from the final retry
  // attempt, and resolveAttachments only ever read that top-level field —
  // so a test that fails twice (each with its own trace file) then passes
  // (with no attachment) lost both failing attempts' traces with no warning.
  it('using the with-retries fixture: resolves attachments from EVERY retry attempt, not just the last', () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-test-'));
    const dataDir = path.join(dir, 'data');
    mkdirSync(dataDir, { recursive: true });
    writeFileSync(path.join(dataDir, 'attempt-1-trace.zip'), 'attempt-1-bytes');
    writeFileSync(path.join(dataDir, 'attempt-2-trace.zip'), 'attempt-2-bytes');

    const raw = readFileSync(path.join(fixturesDir, 'with-retries.json'), 'utf-8');
    const parsed = parseReport(raw);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;

    // Sanity check on the fixture's shape: 3 attempts, first two each carry
    // their own trace attachment, the final (passing) one carries none.
    const test = parsed.value.tests[0];
    expect(test?.retries).toHaveLength(3);

    const result = resolveAttachments(parsed.value, dir);

    // Both failing attempts' trace files must be resolved — this is the
    // crux of the bug: before the fix, result.resolved was empty because
    // resolution only ever looked at the (empty) top-level attachments
    // field, which mirrors only the last, passing attempt.
    expect(result.resolved).toHaveLength(2);
    expect(result.missing).toHaveLength(0);
    const resolvedPaths = result.resolved.map((a) => a.absolutePath).sort();
    expect(resolvedPaths).toEqual(
      [path.join(dataDir, 'attempt-1-trace.zip'), path.join(dataDir, 'attempt-2-trace.zip')].sort(),
    );
    // Each resolved attachment must retain a way to tell which retry
    // attempt produced it, so the manifest can correlate attachment → the
    // right attempt (not just the right test).
    expect(result.resolved.map((a) => a.retryIndex).sort()).toEqual([0, 1]);
  });
});
