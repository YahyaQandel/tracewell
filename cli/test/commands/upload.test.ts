import { describe, expect, it, afterEach } from 'vitest';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { mkdtempSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { runUpload } from '../../src/commands/upload.js';

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

describe('runUpload', () => {
  let server: Server | undefined;
  let dir: string;

  afterEach(async () => {
    if (server) {
      await new Promise<void>((resolve) => server?.close(() => resolve()));
      server = undefined;
    }
    if (dir) rmSync(dir, { recursive: true, force: true });
  });

  it('runs the full pipeline end to end: locate, parse, resolve attachments, upload, format success', async () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-upload-test-'));
    mkdirSync(path.join(dir, 'playwright-report'), { recursive: true });
    writeFileSync(
      path.join(dir, 'playwright-report', 'results.json'),
      JSON.stringify({
        suites: [
          {
            title: 'example.spec.ts',
            specs: [
              {
                title: 'passes',
                tests: [
                  {
                    projectName: 'chromium',
                    results: [{ status: 'passed', duration: 10, retry: 0, attachments: [] }],
                  },
                ],
              },
            ],
          },
        ],
      }),
    );

    const started = await startServer((_req, res) => {
      res.writeHead(201, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ id: 'run-1', url: 'https://tracewell.dev/runs/run-1' }));
    });
    server = started.server;

    const result = await runUpload({
      cwd: dir,
      flags: { apiUrl: started.url, token: 'a-valid-token' },
      env: {},
    });

    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain('https://tracewell.dev/runs/run-1');
  });

  // Regression test for GitHub issue #5: --project / TRACEWELL_PROJECT_ID
  // was resolved by resolveConfig but never forwarded into the actual
  // upload request. This asserts the resolved projectId reaches the real
  // wire payload the server receives, not just that resolveConfig returns it.
  it('forwards the resolved projectId into the actual multipart request body', async () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-upload-test-'));
    mkdirSync(path.join(dir, 'playwright-report'), { recursive: true });
    writeFileSync(
      path.join(dir, 'playwright-report', 'results.json'),
      JSON.stringify({ suites: [] }),
    );

    let receivedBody = '';
    const started = await startServer((req, res) => {
      req.on('data', (chunk) => {
        receivedBody += chunk.toString();
      });
      req.on('end', () => {
        res.writeHead(201, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ id: 'run-proj', url: 'https://tracewell.dev/runs/run-proj' }));
      });
    });
    server = started.server;

    const result = await runUpload({
      cwd: dir,
      flags: { apiUrl: started.url, token: 'a-valid-token', projectId: 'my-special-project-id' },
      env: {},
    });

    expect(result.exitCode).toBe(0);
    expect(receivedBody).toContain('my-special-project-id');
  });

  it('fails fast with ReportNotFoundError copy when the report file is missing', async () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-upload-test-'));

    const result = await runUpload({
      cwd: dir,
      flags: { apiUrl: 'http://127.0.0.1:1', token: 'a-valid-token' },
      env: {},
    });

    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain('no report file found at');
  });
});
