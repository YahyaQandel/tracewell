# tracewell

CLI to upload Playwright test run results (pass/fail outcomes, retries,
screenshots, and trace files) to Tracewell from any CI job or a local
machine.

## Usage

```bash
npx tracewell upload
```

By default this looks for Playwright's JSON reporter output at
`playwright-report/results.json` (the path Playwright's own `json`
reporter writes to by default). Override it with `--report-file` if your
project configures a different output path.

### Flags

| Flag | Description |
|------|-------------|
| `--report-file <path>` | Path to the Playwright JSON reporter output. Overrides the config file and default. |
| `--project <id>` | Tracewell project ID. |
| `--api-url <url>` | Tracewell API URL (for self-hosted/dev instances). Defaults to the production endpoint. |
| `--token <value>` | API token. Overrides `TRACEWELL_API_TOKEN`. Intended for local one-off use — prefer the env var in CI. |

### Auth

Provide a project-scoped API token via the `TRACEWELL_API_TOKEN`
environment variable (a GitHub Actions secret, a GitLab CI masked
variable, or a local `.env`). The `--token` flag takes precedence over the
environment variable when both are present. There is no interactive login
flow — this is a token-only, non-interactive tool by design, matching CI
contexts.

### Config file

An optional `tracewell.config.json` (or `.tracewellrc.json`) at the repo
root can hold non-secret values so they don't need to be repeated as
flags:

```json
{
  "projectId": "my-project",
  "apiUrl": "https://tracewell.example.com",
  "reportFile": "playwright-report/results.json"
}
```

Precedence for every resolved value is **CLI flag > environment variable >
config file > built-in default**. The API token is never read from this
file — only from `TRACEWELL_API_TOKEN` or `--token`.

### Exit codes

`0` on a successful upload, `1` on any failure (network error, invalid
credentials, malformed report, missing report file, server error). CI
systems only need to check success/failure for this tool.

## Development

```bash
npm install
npm test          # run the test suite (vitest)
npm run typecheck # tsc --noEmit
npm run build     # compile to dist/
```
