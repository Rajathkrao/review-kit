# Changelog

Claude Code picks up a new release only when `version` in `.claude-plugin/plugin.json` goes up.
Compare the top entry here with the `rk v…` on a report's Execution line, or with `/plugin` → Installed.

## 1.4.0 · 2026-11-22
- The HTML walkthrough and `findings.json` are kept in the project at
  `.review-kit/reviews/<pr-or-branch>-<time>/` instead of only in a temp folder. The folder ignores
  itself in git. `html_dir` / `--html-out` still choose another folder; `"html_dir": "temp"` keeps
  the old behavior.

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
