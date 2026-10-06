import { createReadStream } from 'node:fs';
import { Readable } from 'node:stream';
import { request } from 'undici';
import type { MultipartRequestSpec } from './buildMultipartRequest.js';
import type { UploadError } from '../errors/UploadError.js';
import { err, ok, type Result } from '../types.js';

export interface UploadSuccess {
  runId: string;
  runUrl: string;
}

export interface UploadTarget {
  apiUrl: string;
  reportFile: string;
  token?: string;
}

export interface RetryOptions {
  maxAttempts?: number;
  baseMs?: number;
  capMs?: number;
}

const DEFAULT_MAX_ATTEMPTS = 3;
const DEFAULT_BASE_MS = 1000;
const DEFAULT_CAP_MS = 5000;

/**
 * I/O: owns the actual network call, streaming multipart construction,
 * retry/backoff loop, and status-code → typed-error classification. The
 * only module allowed to import the HTTP library (undici).
 *
 * Retry policy: transient failures (network error, timeout, 5xx response)
 * are retried with exponential backoff — 3 attempts total, starting at 1s
 * and doubling, capped at ~5s total added latency. 401/403 (bad
 * credentials) and 400 (malformed report) are never retried.
 */
export async function uploadWithRetry(
  spec: MultipartRequestSpec,
  target: UploadTarget,
  retryOptions: RetryOptions = {},
): Promise<Result<UploadSuccess, UploadError>> {
  const maxAttempts = retryOptions.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
  const baseMs = retryOptions.baseMs ?? DEFAULT_BASE_MS;
  const capMs = retryOptions.capMs ?? DEFAULT_CAP_MS;

  let attempt = 0;
  let lastNetworkCause = '';

  while (attempt < maxAttempts) {
    attempt += 1;
    try {
      const response = await postOnce(spec, target);
      const classified = await classifyResponse(response.status, response.body);

      if (classified.ok) {
        return classified;
      }

      if (classified.error.kind === 'Auth' || classified.error.kind === 'MalformedReport') {
        // Deterministic failures — a retry cannot fix these.
        return classified;
      }

      // Server (5xx): transient, retry unless attempts are exhausted.
      if (attempt >= maxAttempts) {
        return err({ ...classified.error, attempts: attempt });
      }
      await delay(backoffMs(attempt, baseMs, capMs));
    } catch (e) {
      lastNetworkCause = e instanceof Error ? e.message : String(e);
      if (attempt >= maxAttempts) {
        return err({
          kind: 'Network',
          apiUrl: target.apiUrl,
          attempts: attempt,
          cause: lastNetworkCause,
        });
      }
      await delay(backoffMs(attempt, baseMs, capMs));
    }
  }

  // Unreachable in practice (loop always returns by the last iteration),
  // but keeps the function total for the type checker.
  return err({ kind: 'Network', apiUrl: target.apiUrl, attempts: attempt, cause: lastNetworkCause });
}

function backoffMs(attempt: number, baseMs: number, capMs: number): number {
  const ms = baseMs * 2 ** (attempt - 1);
  return Math.min(ms, capMs);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function postOnce(
  spec: MultipartRequestSpec,
  target: UploadTarget,
): Promise<{ status: number; body: unknown }> {
  const boundary = `----tracewell-${Math.random().toString(16).slice(2)}`;
  const bodyStream = Readable.from(buildMultipartStream(spec, boundary));

  const headers: Record<string, string> = {
    'content-type': `multipart/form-data; boundary=${boundary}`,
  };
  if (target.token) {
    headers.authorization = `Bearer ${target.token}`;
  }

  const response = await request(new URL('/api/runs/', ensureTrailingSlash(target.apiUrl)), {
    method: 'POST',
    headers,
    body: bodyStream,
  });

  const text = await response.body.text();
  let parsed: unknown = undefined;
  if (text.length > 0) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  return { status: response.statusCode, body: parsed };
}

function ensureTrailingSlash(apiUrl: string): string {
  return apiUrl.endsWith('/') ? apiUrl : `${apiUrl}/`;
}

/**
 * Builds the multipart body as an async generator of Buffer chunks —
 * streaming attachment bytes from disk rather than buffering entire files
 * in memory, per the spec's performance requirement for large trace files.
 */
async function* buildMultipartStream(
  spec: MultipartRequestSpec,
  boundary: string,
): AsyncGenerator<Buffer> {
  yield textPart(boundary, spec.reportPart.fieldName, 'report.json', 'application/json', spec.reportPart.content);
  yield textPart(
    boundary,
    spec.manifestPart.fieldName,
    'manifest.json',
    'application/json',
    spec.manifestPart.content,
  );

  if (spec.projectPart) {
    yield textPart(boundary, spec.projectPart.fieldName, 'project.txt', 'text/plain', spec.projectPart.content);
  }

  for (const attachment of spec.attachmentParts) {
    yield Buffer.from(
      `--${boundary}\r\n` +
        `Content-Disposition: form-data; name="${attachment.fieldName}"; filename="${attachment.filename}"\r\n` +
        `Content-Type: ${attachment.contentType}\r\n\r\n`,
      'utf-8',
    );
    for await (const chunk of createReadStream(attachment.absolutePath)) {
      yield chunk as Buffer;
    }
    yield Buffer.from('\r\n', 'utf-8');
  }

  yield Buffer.from(`--${boundary}--\r\n`, 'utf-8');
}

function textPart(
  boundary: string,
  fieldName: string,
  filename: string,
  contentType: string,
  content: string,
): Buffer {
  return Buffer.from(
    `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="${fieldName}"; filename="${filename}"\r\n` +
      `Content-Type: ${contentType}\r\n\r\n` +
      `${content}\r\n`,
    'utf-8',
  );
}

async function classifyResponse(
  status: number,
  body: unknown,
): Promise<Result<UploadSuccess, UploadError>> {
  if (status === 201) {
    const parsed = body as { id?: unknown; url?: unknown } | undefined;
    const runId = typeof parsed?.id === 'string' ? parsed.id : '';
    const runUrl = typeof parsed?.url === 'string' ? parsed.url : '';
    return ok({ runId, runUrl });
  }

  if (status === 401 || status === 403) {
    return err({ kind: 'Auth', status });
  }

  if (status === 400) {
    const parsed = body as { message?: unknown } | undefined;
    const reason = typeof parsed?.message === 'string' ? parsed.message : 'malformed report';
    return err({ kind: 'MalformedReport', path: '', reason });
  }

  // 5xx (and any other unexpected status) is treated as a server-side,
  // transient-by-default failure.
  return err({
    kind: 'Server',
    status,
    attempts: 1,
    ...(typeof body === 'string' ? { body } : {}),
  });
}
