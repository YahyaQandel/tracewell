import { describe, expect, it } from 'vitest';
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { buildMultipartRequest } from '../../src/upload/buildMultipartRequest.js';
import { parseReport } from '../../src/report/parseReport.js';
import { resolveAttachments } from '../../src/report/resolveAttachments.js';
import type { ParsedRun } from '../../src/types.js';
import type { ResolvedAttachment } from '../../src/report/resolveAttachments.js';

const fixturesDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'fixtures');

describe('buildMultipartRequest', () => {
  it('describes a report part, a manifest part, and one attachment part per resolved attachment', () => {
    const run: ParsedRun = {
      tests: [
        {
          id: 'renders the homepage',
          title: 'renders the homepage',
          outcome: 'passed',
          retries: [
            {
              status: 'passed',
              duration: 10,
              attachments: [{ name: 'screenshot', path: 'homepage.png', contentType: 'image/png' }],
            },
          ],
          attachments: [{ name: 'screenshot', path: 'homepage.png', contentType: 'image/png' }],
        },
      ],
    };
    const resolved: ResolvedAttachment[] = [
      {
        name: 'screenshot',
        contentType: 'image/png',
        absolutePath: '/tmp/fixtures/homepage.png',
        testId: 'renders the homepage',
        retryIndex: 0,
      },
    ];

    const spec = buildMultipartRequest(run, resolved);

    expect(spec.reportPart.fieldName).toBe('report');
    const reportJson = JSON.parse(spec.reportPart.content) as ParsedRun;
    expect(reportJson.tests).toHaveLength(1);

    expect(spec.manifestPart.fieldName).toBe('manifest');
    const manifest = JSON.parse(spec.manifestPart.content) as Array<{
      testId: string;
      attachmentName: string;
      partName: string;
      retryIndex: number;
    }>;
    expect(manifest).toHaveLength(1);
    expect(manifest[0]).toMatchObject({
      testId: 'renders the homepage',
      attachmentName: 'screenshot',
      retryIndex: 0,
    });

    expect(spec.attachmentParts).toHaveLength(1);
    expect(spec.attachmentParts[0]).toMatchObject({
      fieldName: 'attachment[]',
      filename: 'screenshot',
      contentType: 'image/png',
      absolutePath: '/tmp/fixtures/homepage.png',
    });
    // The manifest part's partName must correlate back to this attachment part.
    expect(manifest[0]?.partName).toBe(spec.attachmentParts[0]?.partName);
  });

  it('describes zero attachment parts when no attachments were resolved', () => {
    const run: ParsedRun = { tests: [] };

    const spec = buildMultipartRequest(run, []);

    expect(spec.attachmentParts).toHaveLength(0);
    const manifest = JSON.parse(spec.manifestPart.content) as unknown[];
    expect(manifest).toHaveLength(0);
  });

  // Regression test for GitHub issue #5: a resolved `projectId` was never
  // threaded into the request at all. buildMultipartRequest now accepts an
  // optional projectId and, when present, describes a dedicated `project`
  // text part so the server can associate the run with a project.
  it('describes a project part when a projectId is provided', () => {
    const run: ParsedRun = { tests: [] };

    const spec = buildMultipartRequest(run, [], 'my-special-project-id');

    expect(spec.projectPart).toEqual({ fieldName: 'project', content: 'my-special-project-id' });
  });

  it('omits the project part entirely when no projectId is provided', () => {
    const run: ParsedRun = { tests: [] };

    const spec = buildMultipartRequest(run, []);

    expect(spec.projectPart).toBeUndefined();
  });

  it('does not open or read any file handles — only describes paths', () => {
    const run: ParsedRun = { tests: [] };
    const resolved: ResolvedAttachment[] = [
      {
        name: 'trace',
        contentType: 'application/zip',
        absolutePath: '/this/path/does/not/exist/trace.zip',
        testId: 'nonexistent-test',
        retryIndex: 0,
      },
    ];

    // Should not throw even though the path doesn't exist on disk —
    // buildMultipartRequest only describes what to send, it never opens
    // the file itself (that happens later, at HTTP send time).
    expect(() => buildMultipartRequest(run, resolved)).not.toThrow();
  });

  // Regression test for GitHub issue #6, exercised through the full
  // parse → resolve → build pipeline (not just buildMultipartRequest in
  // isolation): both non-final retry attempts' trace attachments must
  // become real attachment[] parts, each correlated to its own retry via
  // the manifest — not silently dropped because only the last attempt
  // (which has no attachment) used to be consulted.
  it('with-retries fixture end to end: includes an attachment[] part for every retry attempt, not just the last', () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'tracewell-build-test-'));
    try {
      const dataDir = path.join(dir, 'data');
      mkdirSync(dataDir, { recursive: true });
      writeFileSync(path.join(dataDir, 'attempt-1-trace.zip'), 'attempt-1-bytes');
      writeFileSync(path.join(dataDir, 'attempt-2-trace.zip'), 'attempt-2-bytes');

      const raw = readFileSync(path.join(fixturesDir, 'with-retries.json'), 'utf-8');
      const parsed = parseReport(raw);
      expect(parsed.ok).toBe(true);
      if (!parsed.ok) return;

      const { resolved } = resolveAttachments(parsed.value, dir);
      const spec = buildMultipartRequest(parsed.value, resolved);

      expect(spec.attachmentParts).toHaveLength(2);
      const manifest = JSON.parse(spec.manifestPart.content) as Array<{
        testId: string;
        attachmentName: string;
        partName: string;
        retryIndex: number;
      }>;
      expect(manifest).toHaveLength(2);
      expect(manifest.map((m) => m.retryIndex).sort()).toEqual([0, 1]);
      // Every manifest entry's partName must correlate to a real attachment part.
      const partNames = spec.attachmentParts.map((p) => p.partName).sort();
      expect(manifest.map((m) => m.partName).sort()).toEqual(partNames);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
