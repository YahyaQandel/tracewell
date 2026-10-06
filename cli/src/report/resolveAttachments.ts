import { existsSync } from 'node:fs';
import path from 'node:path';
import type { ParsedRun } from '../types.js';

export interface ResolvedAttachment {
  name: string;
  contentType: string;
  absolutePath: string;
  testId: string;
  /** Index into `ParsedTest.retries` identifying which attempt produced this attachment. */
  retryIndex: number;
}

export interface MissingAttachment {
  name: string;
  contentType: string;
  referencedPath: string;
  testId: string;
  /** Index into `ParsedTest.retries` identifying which attempt referenced this attachment. */
  retryIndex: number;
}

export interface ResolvedAttachmentSet {
  resolved: ResolvedAttachment[];
  missing: MissingAttachment[];
}

export interface ResolveAttachmentsOptions {
  /** Called once per missing attachment with a human-readable warning message. */
  onMissing?: (message: string) => void;
}

/**
 * I/O + pure mix: resolves each attachment's path relative to the report
 * file's directory, stats each file, and returns resolved vs. missing
 * attachments. Emits one warning per missing attachment as a side effect
 * (via `onMissing`, defaulting to `console.warn`) and does not fail the
 * pipeline — a missing attachment is reported, not thrown.
 *
 * Walks every retry attempt's `attachments` (`test.retries[i].attachments`),
 * not just the top-level `test.attachments` field — the top-level field
 * mirrors only the *last* attempt's attachments (see parseReport.ts), so a
 * test that fails on earlier attempts with its own trace/screenshot per
 * attempt would otherwise have those earlier attachments silently
 * unresolved and never uploaded (GitHub issue #6). Each resolved/missing
 * attachment is tagged with `retryIndex` so the manifest can correlate it
 * back to the specific attempt that produced it, not just the test.
 *
 * Does not read file *contents* — streaming happens later, at upload time.
 */
export function resolveAttachments(
  run: ParsedRun,
  reportDir: string,
  options: ResolveAttachmentsOptions = {},
): ResolvedAttachmentSet {
  const onMissing = options.onMissing ?? defaultOnMissing;
  const resolved: ResolvedAttachment[] = [];
  const missing: MissingAttachment[] = [];

  for (const test of run.tests) {
    test.retries.forEach((retry, retryIndex) => {
      for (const attachment of retry.attachments) {
        if (!attachment.path) {
          // Attachments without a path (e.g. inline body attachments) are
          // not file-backed and have nothing to resolve on disk.
          continue;
        }
        const absolutePath = path.resolve(reportDir, attachment.path);
        if (existsSync(absolutePath)) {
          resolved.push({
            name: attachment.name,
            contentType: attachment.contentType,
            absolutePath,
            testId: test.id,
            retryIndex,
          });
        } else {
          missing.push({
            name: attachment.name,
            contentType: attachment.contentType,
            referencedPath: attachment.path,
            testId: test.id,
            retryIndex,
          });
          onMissing(
            `tracewell upload: warning — attachment "${attachment.name}" for test "${test.title}" (attempt ${retryIndex + 1}) was not found at ${absolutePath}, continuing without it.`,
          );
        }
      }
    });
  }

  return { resolved, missing };
}

function defaultOnMissing(message: string): void {
  console.warn(message);
}
