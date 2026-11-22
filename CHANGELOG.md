# Changelog

Claude Code picks up a new release only when `version` in `.claude-plugin/plugin.json` goes up.
Compare the top entry here with the `rk v…` on a report's Execution line, or with `/plugin` → Installed.

## 1.5.0 · 2026-11-22
- Clearer PR comments from `/rk:pr --post`: verdict heading with severity counts, a one-line-per-issue
  table, and folded sections for out-of-diff issues, minor issues, agreed comments and an AI fix prompt.
- Inline comments lead with a severity icon and title, keep evidence folded, and add a copyable
  "Prompt for AI agents". Minor findings no longer post inline.
- A one-click suggestion is offered only when the comment covers the finding's whole line range,
  so GitHub can't apply it to the wrong lines. Code fences survive backticks in the code.

## 1.3.0 · 2026-11-22
- Reports and the HTML footer show which review-kit version produced them.
- README: which command to run when, where results are written, how to update and check your version.
- CI fails a PR that changes the plugin without bumping its version.

## 1.2.0 · 2026-11-16
- Refine: structure map, up to three structural moves, measured before/after, safer `--apply` (#30).
- Also first release to carry #21–#29, which landed without a version bump: walkthrough with
  architecture, sequence and module diagrams; `/rk:explain`; `/rk:fix`; faster deep runs; problems
  at a glance with copyable fix prompts; no findings for code that doesn't exist yet.

## 1.1.0 · 2026-11-12
- `/rk:refine`: simplify, reuse and refactor mode with `--apply` (#20).

## 1.0.0 · 2026-11-12
- Fast core: one context call, a verifier that never drops a candidate without a disproof, Python lens (#19).

## 0.3.0 · 2026-10-24
- First release: purpose-aware, verified code review plugin.
