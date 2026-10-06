import { describe, expect, it, vi, afterEach } from 'vitest';
import { main } from '../../src/bin/tracewell.js';

/**
 * Regression tests for GitHub issue #4: any unhandled exception — --help,
 * upload --help, no subcommand, unknown subcommand, unknown flag, or a
 * corrupt config file — used to crash main() with a raw, uncaught
 * CommanderError (or SyntaxError) stack trace instead of exiting cleanly.
 *
 * These drive main() directly (exported from src/bin/tracewell.ts) rather
 * than spawning a subprocess, since main() itself is the seam that must
 * never throw — it is the one place that owns turning any thrown error
 * into a clean exit code.
 */
describe('main', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('exits 0 and does not throw on --help', async () => {
    const exitCode = await main(['--help']);
    expect(exitCode).toBe(0);
  });

  it('exits 0 and does not throw on upload --help', async () => {
    const exitCode = await main(['upload', '--help']);
    expect(exitCode).toBe(0);
  });

  it('exits non-zero and does not throw with no subcommand', async () => {
    const exitCode = await main([]);
    expect(exitCode).toBe(1);
  });

  it('exits non-zero and does not throw on an unknown subcommand', async () => {
    const exitCode = await main(['bogus-command']);
    expect(exitCode).toBe(1);
  });

  it('exits non-zero and does not throw on an unknown flag', async () => {
    const exitCode = await main(['upload', '--bogus-flag', 'value', '--api-url', 'http://127.0.0.1:1', '--token', 't']);
    expect(exitCode).toBe(1);
  });
});
