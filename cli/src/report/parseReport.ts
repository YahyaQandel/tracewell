import type { MalformedReportError } from '../errors/UploadError.js';
import { err, ok, type AttachmentRef, type ParsedRun, type ParsedTest, type Result, type RetryAttempt, type TestOutcome } from '../types.js';

/**
 * Pure: parses Playwright JSON reporter output into the CLI's internal
 * `ParsedRun` shape. No filesystem or network access — takes already-read
 * file content, not a path.
 */
export function parseReport(raw: string): Result<ParsedRun, MalformedReportError> {
  let json: unknown;
  try {
    json = JSON.parse(raw);
  } catch (e) {
    return err({
      kind: 'MalformedReport',
      path: '',
      reason: e instanceof Error ? e.message : 'invalid JSON',
    });
  }

  if (typeof json !== 'object' || json === null || !('suites' in json)) {
    return err({
      kind: 'MalformedReport',
      path: '',
      reason: 'missing "suites" array at top level',
    });
  }

  const suites = (json as { suites: unknown }).suites;
  if (!Array.isArray(suites)) {
    return err({
      kind: 'MalformedReport',
      path: '',
      reason: '"suites" must be an array',
    });
  }

  const tests: ParsedTest[] = [];

  try {
    for (const suite of suites) {
      collectSpecs(suite, tests);
    }
  } catch (e) {
    return err({
      kind: 'MalformedReport',
      path: '',
      reason: e instanceof Error ? e.message : 'unexpected report shape',
    });
  }

  return ok({ tests });
}

function collectSpecs(suite: unknown, out: ParsedTest[]): void {
  if (typeof suite !== 'object' || suite === null) {
    throw new Error('suite entry is not an object');
  }
  const specs = (suite as { specs?: unknown }).specs;
  if (specs === undefined) {
    // Nested suites (Playwright nests suites for file > describe blocks).
    const nestedSuites = (suite as { suites?: unknown }).suites;
    if (Array.isArray(nestedSuites)) {
      for (const nested of nestedSuites) {
        collectSpecs(nested, out);
      }
    }
    return;
  }
  if (!Array.isArray(specs)) {
    throw new Error('"specs" must be an array');
  }

  for (const spec of specs) {
    out.push(parseSpec(spec));
  }
}

function parseSpec(spec: unknown): ParsedTest {
  if (typeof spec !== 'object' || spec === null) {
    throw new Error('spec entry is not an object');
  }
  const title = (spec as { title?: unknown }).title;
  if (typeof title !== 'string') {
    throw new Error('spec "title" must be a string');
  }

  const testsField = (spec as { tests?: unknown }).tests;
  const specTests = Array.isArray(testsField) ? testsField : [];

  // A spec may run under multiple Playwright "projects" (e.g. chromium +
  // firefox in one JSON report) — specTests would then have more than one
  // entry. This intentionally takes only the first project's results as
  // the authoritative retry history; other projects' results are not
  // merged in or reported separately. Explicitly out of scope for TW-1
  // (see arch-review.md's "multi-project Playwright report gap" finding
  // and dev-report.md's Bug Fix Iteration 2 section for the developer's
  // ruling): neither of TW-1's user stories mentions multi-project
  // matrices, and `id`/`testId` here is a wire-contract value TW-2 (not
  // yet built) will consume — reshaping it to be unique per (spec ×
  // project) is a decision for TW-2's architect, not a unilateral change
  // here. Revisit when a team running a multi-project CI matrix adopts
  // this CLI, or when TW-2 defines how it wants multi-project specs
  // represented.
  const firstTest = specTests[0] as { results?: unknown } | undefined;
  const results = Array.isArray(firstTest?.results) ? (firstTest.results as unknown[]) : [];

  const retries: RetryAttempt[] = results.map(parseResult);
  const lastResult = retries[retries.length - 1];
  const outcome = classifyOutcome(retries, lastResult);
  const attachments = lastResult ? lastResult.attachments : [];

  return {
    id: title,
    title,
    outcome,
    retries,
    attachments,
  };
}

function parseResult(result: unknown): RetryAttempt {
  if (typeof result !== 'object' || result === null) {
    throw new Error('result entry is not an object');
  }
  const status = (result as { status?: unknown }).status;
  if (
    status !== 'passed' &&
    status !== 'failed' &&
    status !== 'timedOut' &&
    status !== 'skipped' &&
    status !== 'interrupted'
  ) {
    throw new Error(`unrecognized result status: ${String(status)}`);
  }
  const duration = (result as { duration?: unknown }).duration;
  const attachmentsField = (result as { attachments?: unknown }).attachments;
  const attachments: AttachmentRef[] = Array.isArray(attachmentsField)
    ? attachmentsField.map(parseAttachment)
    : [];

  return {
    status,
    duration: typeof duration === 'number' ? duration : 0,
    attachments,
  };
}

function parseAttachment(attachment: unknown): AttachmentRef {
  if (typeof attachment !== 'object' || attachment === null) {
    throw new Error('attachment entry is not an object');
  }
  const name = (attachment as { name?: unknown }).name;
  const contentType = (attachment as { contentType?: unknown }).contentType;
  const attachmentPath = (attachment as { path?: unknown }).path;
  if (typeof name !== 'string') {
    throw new Error('attachment "name" must be a string');
  }
  if (typeof contentType !== 'string') {
    throw new Error('attachment "contentType" must be a string');
  }
  return {
    name,
    contentType,
    ...(typeof attachmentPath === 'string' ? { path: attachmentPath } : {}),
  };
}

function classifyOutcome(retries: RetryAttempt[], lastResult: RetryAttempt | undefined): TestOutcome {
  if (retries.length === 0) {
    return 'skipped';
  }
  if (!lastResult) {
    return 'skipped';
  }
  if (lastResult.status === 'skipped') {
    return 'skipped';
  }
  if (lastResult.status === 'passed') {
    return retries.length > 1 ? 'flaky' : 'passed';
  }
  return 'failed';
}
