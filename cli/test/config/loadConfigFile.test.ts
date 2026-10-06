import { describe, expect, it, afterEach } from 'vitest';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { loadConfigFile } from '../../src/config/loadConfigFile.js';

describe('loadConfigFile', () => {
  let dir: string;

  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true });
  });

  it('returns undefined when no config file is present', () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-config-test-'));

    const result = loadConfigFile(dir);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value).toBeUndefined();
  });

  it('parses a valid config file', () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-config-test-'));
    writeFileSync(
      path.join(dir, 'tracewell.config.json'),
      JSON.stringify({ projectId: 'proj-1', apiUrl: 'https://dev.example.com' }),
    );

    const result = loadConfigFile(dir);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value).toMatchObject({ projectId: 'proj-1', apiUrl: 'https://dev.example.com' });
  });

  // Regression test for GitHub issue #4 (bundled bug, TC-022): a corrupt
  // tracewell.config.json used to crash with a raw, unhandled SyntaxError
  // from JSON.parse instead of flowing through the typed UploadError /
  // formatResult pipeline every other failure mode uses.
  it('returns a typed MalformedConfigError instead of throwing when the config file has invalid JSON', () => {
    dir = mkdtempSync(path.join(tmpdir(), 'tracewell-config-test-'));
    writeFileSync(path.join(dir, 'tracewell.config.json'), '{ broken json config ');

    let result: ReturnType<typeof loadConfigFile> | undefined;
    expect(() => {
      result = loadConfigFile(dir);
    }).not.toThrow();

    expect(result?.ok).toBe(false);
    if (!result || result.ok) return;
    expect(result.error.kind).toBe('MalformedConfig');
    expect(result.error.path).toContain('tracewell.config.json');
  });
});
