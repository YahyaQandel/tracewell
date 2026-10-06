import type { ParsedRun } from '../types.js';
import type { ResolvedAttachment } from '../report/resolveAttachments.js';

export interface ReportPart {
  fieldName: 'report';
  content: string;
}

export interface ManifestEntry {
  testId: string;
  attachmentName: string;
  partName: string;
  /** Which retry attempt (index into ParsedTest.retries) produced this attachment. */
  retryIndex: number;
}

export interface ManifestPart {
  fieldName: 'manifest';
  content: string;
}

export interface ProjectPart {
  fieldName: 'project';
  content: string;
}

export interface AttachmentPart {
  fieldName: 'attachment[]';
  /** Unique part name correlated to a manifest entry's `partName`. */
  partName: string;
  filename: string;
  contentType: string;
  absolutePath: string;
}

export interface MultipartRequestSpec {
  reportPart: ReportPart;
  manifestPart: ManifestPart;
  attachmentParts: AttachmentPart[];
  /** Present only when a projectId was resolved (--project / TRACEWELL_PROJECT_ID / config file). */
  projectPart?: ProjectPart;
}

/**
 * Pure (given already-resolved paths): describes the multipart body shape
 * (`report`, `manifest`, `attachment[]`, and optionally `project` parts) as
 * a spec object consumed by the HTTP layer. Does not itself open file
 * handles — keeps this module unit-testable without touching disk.
 * Streaming the actual bytes happens in httpClient.ts at send time.
 *
 * `projectId` (GitHub issue #5): when resolveConfig resolves a project ID
 * (via --project / TRACEWELL_PROJECT_ID / config file's `projectId`), it
 * must actually reach the server. design.md left the exact wire location
 * open ("your call, consistent with design.md's multipart part structure").
 * Chosen here: a dedicated `project` text part, sibling to `report` and
 * `manifest` — simplest for the server to read (a plain field, no reshaping
 * of the existing manifest array), optional (omitted entirely when no
 * projectId was resolved, so existing/non-multi-project servers see no
 * change in the request shape).
 */
export function buildMultipartRequest(
  run: ParsedRun,
  resolved: ResolvedAttachment[],
  projectId?: string,
): MultipartRequestSpec {
  const reportPart: ReportPart = {
    fieldName: 'report',
    content: JSON.stringify(run),
  };

  const attachmentParts: AttachmentPart[] = [];
  const manifestEntries: ManifestEntry[] = [];

  resolved.forEach((attachment, index) => {
    const partName = `attachment-${index}`;
    attachmentParts.push({
      fieldName: 'attachment[]',
      partName,
      filename: attachment.name,
      contentType: attachment.contentType,
      absolutePath: attachment.absolutePath,
    });
    manifestEntries.push({
      testId: attachment.testId,
      attachmentName: attachment.name,
      partName,
      retryIndex: attachment.retryIndex,
    });
  });

  const manifestPart: ManifestPart = {
    fieldName: 'manifest',
    content: JSON.stringify(manifestEntries),
  };

  return {
    reportPart,
    manifestPart,
    attachmentParts,
    ...(projectId !== undefined ? { projectPart: { fieldName: 'project', content: projectId } } : {}),
  };
}
