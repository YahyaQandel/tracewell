<img src="assets/logo.svg" alt="Tracewell" width="240">

A Playwright test-reporting dashboard. CI uploads run results — pass/fail outcomes, retries, screenshots, and traces — and Tracewell shows run history, failures, flaky tests, and trends, so the team doesn't have to dig through CI logs.

## Status

| Piece | Status |
|---|---|
| CLI uploader (`npx tracewell upload`) | Built & tested — see [`cli/`](cli/) |
| Ingestion API | Not started |
| Dashboard (runs, run detail, flaky, analysis) | Designed only — [interactive mockup](https://claude.ai/artifact/44NppEKmPT51ZZ7gok4BXH) |

This is a walking-skeleton build, one vertical slice at a time. See [GitHub Issues](https://github.com/YahyaQandel/tracewell/issues) and the [project board](https://github.com/users/YahyaQandel/projects/6) for what's in flight.

## CLI

```bash
npx tracewell upload
```

Reads Playwright's JSON reporter output, bundles every attachment it references, and uploads it in one request. Full usage: [`cli/README.md`](cli/README.md).

## Development

This project is built via an agent pipeline: each ticket goes through product-owner spec → architect design → TDD implementation → review → testing before merge. Config lives in [`pipeline.toml`](pipeline.toml).

```bash
cd cli
npm install
npm test
```
