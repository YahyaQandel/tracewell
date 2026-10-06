#!/usr/bin/env node
import { Command, CommanderError } from 'commander';
import { runUpload } from '../commands/upload.js';
import type { ParsedFlags } from '../config/resolveConfig.js';

/**
 * Executable entry point. Parses argv, dispatches to the `upload`
 * subcommand, maps the result to a process exit code. Zero business logic
 * — all of that lives in commands/upload.ts and below.
 */

/**
 * Pure: parses an `upload` subcommand argv into flags. Exported for tests.
 *
 * `exitOverride()` makes commander throw a `CommanderError` instead of
 * calling `process.exit()` itself on --help/usage errors/unknown
 * options/commands, so that this function stays a plain function `main()`
 * can call and handle a thrown result from (see `main()` below for the
 * catch — GitHub issue #4). Commander's own output writers (help text,
 * "unknown option" messages, etc.) are left at their default — writing to
 * the real stdout/stderr — since that text is exactly what a CLI user
 * expects to see for --help and usage errors; only the *exit* behavior is
 * overridden, not the output.
 */
export function parseUploadArgv(argv: string[]): ParsedFlags {
  const program = new Command();
  program.exitOverride();

  let flags: ParsedFlags = {};

  program
    .command('upload', { isDefault: false })
    .option('--report-file <path>', 'path to the Playwright JSON reporter output')
    .option('--project <id>', 'project ID')
    .option('--api-url <url>', 'Tracewell API URL')
    .option('--token <value>', 'API token (overrides TRACEWELL_API_TOKEN)')
    .action((opts: { reportFile?: string; project?: string; apiUrl?: string; token?: string }) => {
      flags = {
        ...(opts.reportFile !== undefined ? { reportFile: opts.reportFile } : {}),
        ...(opts.project !== undefined ? { projectId: opts.project } : {}),
        ...(opts.apiUrl !== undefined ? { apiUrl: opts.apiUrl } : {}),
        ...(opts.token !== undefined ? { token: opts.token } : {}),
      };
    });

  program.parse(argv, { from: 'user' });

  return flags;
}

/**
 * Dispatches argv parsing + the upload pipeline, and is the single place
 * that converts ANY exception — not just typed `UploadError`s — into a
 * clean exit code (GitHub issue #4). Before this fix, `parseUploadArgv`'s
 * thrown `CommanderError` (from --help, usage errors, unknown
 * commands/options — see `exitOverride()` above) had nothing catching it
 * here, so it propagated as a raw, unhandled stack trace and (for --help
 * specifically) Node's uncaught-exception default exit code of 1 was used
 * instead of commander's own `CommanderError.exitCode: 0` for a
 * successfully-displayed help screen.
 *
 * `CommanderError` already carries the correct exit code and has already
 * written its own clean output (help text / "unknown option: ..." / etc.)
 * via commander's default writers — see the comment on `parseUploadArgv`
 * — so this handler writes nothing further, it only relays `exitCode`.
 */
export async function main(argv: string[]): Promise<number> {
  let flags: ParsedFlags;
  try {
    flags = parseUploadArgv(argv);
  } catch (e) {
    if (e instanceof CommanderError) {
      return e.exitCode;
    }
    // Any other unexpected throw during argv parsing: fail clearly rather
    // than crash with a raw stack trace.
    process.stderr.write(`tracewell upload: unexpected error — ${e instanceof Error ? e.message : String(e)}\n`);
    return 1;
  }

  const result = await runUpload({
    cwd: process.cwd(),
    flags,
    env: process.env,
  });

  if (result.stdout) {
    process.stdout.write(`${result.stdout}\n`);
  }
  if (result.stderr) {
    process.stderr.write(`${result.stderr}\n`);
  }

  return result.exitCode;
}

const isMainModule = process.argv[1] !== undefined && import.meta.url === new URL(process.argv[1], 'file://').href;

if (isMainModule) {
  main(process.argv.slice(2)).then((exitCode) => {
    process.exit(exitCode);
  });
}
