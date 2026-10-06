import { describe, expect, it, afterEach } from 'vitest';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { uploadWithRetry } from '../../src/upload/httpClient.js';
import type { MultipartRequestSpec } from '../../src/upload/buildMultipartRequest.js';

/** Starts a mock HTTP server whose handler is supplied per-test. */
function startServer(
  handler: (req: import('node:http').IncomingMessage, res: import('node:http').ServerResponse) => void,
): Promise<{ server: Server; url: string }> {
  return new Promise((resolve) => {
    const server = createServer(handler);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as AddressInfo;
      resolve({ server, url: `http://127.0.0.1:${port}` });
    });
  });
}

function minimalSpec(): MultipartRequestSpec {
  return {
    reportPart: { fieldName: 'report', content: '{"tests":[]}' },
    manifestPart: { fieldName: 'manifest', content: '[]' },
    attachmentParts: [],
  };
}

describe('uploadWithRetry', () => {
  let server: Server | undefined;
  let dir: string;

  afterEach(async () => {
    if (server) {
      await new Promise<void>((resolve) => server?.close(() => resolve()));
      server = undefined;
    }
    if (dir) rmSync(dir, { recursive: true, force: true });
  });

  it('returns UploadSuccess with the run URL on 201 Created', async () => {
    const started = await startServer((_req, res) => {
      res.writeHead(201, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ id: 'run-123', url: 'https://tracewell.dev/runs/run-123' }));
    });
    server = started.server;

    const result = await uploadWithRetry(minimalSpec(), {
      apiUrl: started.url,
      reportFile: 'playwright-report/results.json',
      token: 'valid-token',
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.runUrl).toBe('https://tracewell.dev/runs/run-123');
  });

  it('classifies 401 as AuthError and does not retry', async () => {
    let requestCount = 0;
    const started = await startServer((_req, res) => {
      requestCount += 1;
      res.writeHead(401, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ message: 'bad token' }));
    });
    server = started.server;

    const result = await uploadWithRetry(minimalSpec(), {
      apiUrl: started.url,
      reportFile: 'playwright-report/results.json',
      token: 'bad-token',
    });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe('Auth');
    expect(requestCount).toBe(1);
  });

  it('classifies 400 as MalformedReportError and does not retry', async () => {
    let requestCount = 0;
    const started = await startServer((_req, res) => {
      requestCount += 1;
      res.writeHead(400, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ message: 'bad report shape' }));
    });
    server = started.server;

    const result = await uploadWithRetry(minimalSpec(), {
      apiUrl: started.url,
      reportFile: 'playwright-report/results.json',
      token: 'valid-token',
    });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe('MalformedReport');
    expect(requestCount).toBe(1);
  });

  it('retries a 5xx response up to 3 attempts total, then returns ServerError', async () => {
    let requestCount = 0;
    const started = await startServer((_req, res) => {
      requestCount += 1;
      res.writeHead(503, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ message: 'service unavailable' }));
    });
    server = started.server;

    const result = await uploadWithRetry(
      minimalSpec(),
      { apiUrl: started.url, reportFile: 'playwright-report/results.json', token: 'valid-token' },
      { baseMs: 1 }, // keep the test fast; backoff timing itself isn't the assertion
    );

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe('Server');
    expect(requestCount).toBe(3);
  });

  it('retries a network-level failure (connection refused) up to 3 attempts, then returns NetworkError', async () => {
    // Nothing listening on this port — connection refused every attempt.
    const result = await uploadWithRetry(
      minimalSpec(),
      { apiUrl: 'http://127.0.0.1:1', reportFile: 'playwright-report/results.json', token: 'valid-token' },
      { baseMs: 1 },
    );

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe('Network');
    if (result.error.kind === 'Network') {
      expect(result.error.attempts).toBe(3);
    }
  });

  it('succeeds on the second attempt after one transient 503, without exhausting all retries', async () => {
    let requestCount = 0;
    const started = await startServer((_req, res) => {
      requestCount += 1;
      if (requestCount === 1) {
        res.writeHead(503, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ message: 'service unavailable' }));
        return;
      }
      res.writeHead(201, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ id: 'run-456', url: 'https://tracewell.dev/runs/run-456' }));
    });
    server = started.server;

    const result = await uploadWithRetry(
      minimalSpec(),
      { apiUrl: started.url, reportFile: 'playwright-report/results.json', token: 'valid-token' },
      { baseMs: 1 },
    );

    expect(result.ok).toBe(true);
    expect(requestCount).toBe(2);
  });

  it('streams attachment file bytes from disk rather than requiring them pre-loaded into the spec', async () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-test-'));
    const filePath = path.join(dir, 'trace.zip');
    writeFileSync(filePath, 'fake-trace-bytes');

    let receivedBody = '';
    const started = await startServer((req, res) => {
      req.on('data', (chunk) => {
        receivedBody += chunk.toString();
      });
      req.on('end', () => {
        res.writeHead(201, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ id: 'run-789', url: 'https://tracewell.dev/runs/run-789' }));
      });
    });
    server = started.server;

    const spec: MultipartRequestSpec = {
      reportPart: { fieldName: 'report', content: '{"tests":[]}' },
      manifestPart: { fieldName: 'manifest', content: '[]' },
      attachmentParts: [
        {
          fieldName: 'attachment[]',
          partName: 'attachment-0',
          filename: 'trace.zip',
          contentType: 'application/zip',
          absolutePath: filePath,
        },
      ],
    };

    const result = await uploadWithRetry(spec, {
      apiUrl: started.url,
      reportFile: 'playwright-report/results.json',
      token: 'valid-token',
    });

    expect(result.ok).toBe(true);
    expect(receivedBody).toMatch(/fake-trace-bytes/);
  });
});
