import { describe, expect, it } from 'vitest';
import { resolveConfig, type ParsedFlags } from '../../src/config/resolveConfig.js';
import type { ConfigFile } from '../../src/config/loadConfigFile.js';

const DEFAULT_API_URL = 'https://api.tracewell.dev';
const DEFAULT_REPORT_FILE = 'playwright-report/results.json';

function flags(overrides: Partial<ParsedFlags> = {}): ParsedFlags {
  return { ...overrides };
}

describe('resolveConfig', () => {
  it('falls back to built-in defaults when nothing else is provided', () => {
    const result = resolveConfig(flags(), {}, undefined);

    expect(result).toMatchObject({
      apiUrl: DEFAULT_API_URL,
      reportFile: DEFAULT_REPORT_FILE,
    });
    expect(result.token).toBeUndefined();
    expect(result.projectId).toBeUndefined();
  });

  it('prefers the config file over defaults', () => {
    const configFile: ConfigFile = {
      projectId: 'proj-from-file',
      apiUrl: 'https://file.example.com',
      reportFile: 'custom/results.json',
    };

    const result = resolveConfig(flags(), {}, configFile);

    expect(result.projectId).toBe('proj-from-file');
    expect(result.apiUrl).toBe('https://file.example.com');
    expect(result.reportFile).toBe('custom/results.json');
  });

  it('prefers an environment variable over the config file', () => {
    const configFile: ConfigFile = { apiUrl: 'https://file.example.com' };
    const env = { TRACEWELL_API_URL: 'https://env.example.com' };

    const result = resolveConfig(flags(), env, configFile);

    expect(result.apiUrl).toBe('https://env.example.com');
  });

  it('prefers a CLI flag over an environment variable', () => {
    const env = { TRACEWELL_API_URL: 'https://env.example.com' };

    const result = resolveConfig(flags({ apiUrl: 'https://flag.example.com' }), env, undefined);

    expect(result.apiUrl).toBe('https://flag.example.com');
  });

  it('resolves the token from TRACEWELL_API_TOKEN when no --token flag is given', () => {
    const env = { TRACEWELL_API_TOKEN: 'env-token-value' };

    const result = resolveConfig(flags(), env, undefined);

    expect(result.token).toBe('env-token-value');
  });

  it('prefers the --token flag over the TRACEWELL_API_TOKEN env var', () => {
    const env = { TRACEWELL_API_TOKEN: 'env-token-value' };

    const result = resolveConfig(flags({ token: 'flag-token-value' }), env, undefined);

    expect(result.token).toBe('flag-token-value');
  });

  it('never reads the token from the config file, even if present there', () => {
    // A config file is non-secret by contract; `token` is deliberately not
    // part of the ConfigFile type, so this models a hostile/malformed file
    // that includes it anyway, cast past the type to prove resolveConfig
    // ignores it.
    const configFile = { token: 'should-never-be-read' } as unknown as ConfigFile;

    const result = resolveConfig(flags(), {}, configFile);

    expect(result.token).toBeUndefined();
  });
});
