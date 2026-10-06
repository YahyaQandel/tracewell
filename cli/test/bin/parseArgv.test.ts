import { describe, expect, it } from 'vitest';
import { parseUploadArgv } from '../../src/bin/tracewell.js';

describe('parseUploadArgv', () => {
  it('parses --report-file, --project, --api-url, and --token flags', () => {
    const flags = parseUploadArgv([
      'upload',
      '--report-file',
      'custom/results.json',
      '--project',
      'proj-1',
      '--api-url',
      'https://dev.tracewell.example.com',
      '--token',
      'tok-abc',
    ]);

    expect(flags).toEqual({
      reportFile: 'custom/results.json',
      projectId: 'proj-1',
      apiUrl: 'https://dev.tracewell.example.com',
      token: 'tok-abc',
    });
  });

  it('parses with no flags into an empty flags object', () => {
    const flags = parseUploadArgv(['upload']);

    expect(flags).toEqual({});
  });
});
