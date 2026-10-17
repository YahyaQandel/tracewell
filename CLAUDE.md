# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Tracewell: a Playwright test-reporting dashboard. See [README.md](README.md) for what's built vs. designed-only, and [pipeline.toml](pipeline.toml) for the stack and tooling this project's agent pipeline reads.

This project is built via the `agent-sdlc-pipeline` plugin (`@orchestrator`, `@product-owner`, `@developer`, `@architect-reviewer`, `@manual-tester`, `@automation-tester`) — see `~/code/claude-plugins/agent-sdlc-pipeline/README.md` for the pipeline itself. The rules below are this project's own policy on top of that pipeline; where the two overlap, this file is the specific case and the plugin is the general mechanism.

## Workflow

- **One git worktree per issue.** Never work on a ticket directly in the main checkout, and never share a worktree between two tickets. `git worktree add ../tracewell-<ISSUE-ID> -b <ISSUE-ID>-<slug>` — see the orchestrator's Step 0.
- **Branch name carries the issue ID**: `<ISSUE-ID>-<slug>`, e.g. `TW-12-runs-list`. Not a bare `feature/<slug>`.
- **Issue status changes with the work, not after it**: set to "In Progress" (or this repo's equivalent) when work starts, and to "In Review" the moment a PR is opened — both are orchestrator steps, not an afterthought at the end.
- **TDD, strictly.** A failing test exists before the implementation that makes it pass. No exceptions for "small" changes.
- **All tests pass before every commit** — not just at the end of implementation. Run `cd cli && npm test` (or this project's current `[project.stack].test_command`) immediately before each commit.
- **A story is done only when both hold**: the implementation matches `design.md` with no undocumented deviations, AND every acceptance criterion in the spec is met. Neither alone is sufficient — a faithful-to-design implementation that misses an acceptance criterion is not done, and a criterion-satisfying implementation that ignores the approved design is not done either.
- **Every acceptance criterion has a real test.** Not "mostly covered" — each criterion in a story's spec maps to at least one test that actually exercises it, verified by the architect-reviewer's traceability table in CONFORMANCE mode, not just claimed by the developer.
- **After a PR is opened, review it from a fresh session.** The session that wrote the code does not review its own PR — that's the same context re-reading itself, not an independent check. Open a new Claude Code session (or dispatch a subagent with no prior context) and run the `code-review` skill against the PR diff, the spec, and `design.md` — nothing else. If no mechanism to start a fresh session is available, say so explicitly rather than reviewing inline and calling it done.

## Commits and PRs

- **Issue ID in every commit message** — prefix (`TW-12: ...`) or trailer, pick one and stay consistent within a branch.
- **No AI/assistant attribution anywhere** — not in commits, not in PR descriptions. No `Co-Authored-By: Claude`, no "Generated with Claude Code" footer, no mention of any AI tool. This repo's commits and PRs are authored by the user. (This is enforced globally for this account via `attribution.commitAttribution: false` / `prAttribution: false`, and restated here because it's load-bearing for this project's process, not incidental.)
- **Never push without explicit go-ahead for that specific push.** Committing locally is fine; publishing is a separate decision each time.

## Running tests

```bash
cd cli
npm install
npm test          # vitest
npm run typecheck  # tsc --noEmit
npm run build
```

CI runs the same commands on every push/PR to `main` — see `.github/workflows/test.yml`.

## Stack

See `[project.stack]` in `pipeline.toml` — it's the single source of truth agents read before writing code, not duplicated here so it can't drift out of sync.
