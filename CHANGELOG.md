# Changelog

Claude Code picks up a new release only when `version` in `.claude-plugin/plugin.json` goes up.
Compare the top entry here with the `rk v…` on a report's Execution line, or with `/plugin` → Installed.

## 1.7.0 · 2026-11-22
- HTML report redesign: a slim sticky top bar (repo, branch, commit, verdict, theme), a modern sans
  type scale, stat tiles for size, effort, problems and tests, a verdict card with severity filters,
  numbered sections, and each problem as its own card with a severity badge. Tuned light and dark
  themes; works at phone width without sideways scrolling.
- The contents rail is wider; problem and step titles are clamped to two lines with the full title
  on hover, severity dots, and counts next to each section.
- "Python modules touched" is now a three-column map (uses the change, changed, builds on) at full
  size instead of one long row of shrunken boxes. Imports now resolve in nested `src/` layouts
  (`pkg/src/pkg/...` in a monorepo) and by unique dotted suffix, so the arrows appear.
- Architecture diagrams wrap any row wider than four boxes onto a new row.
- `evals/build_walkthrough_large.py` builds a 12-file, 7-finding package to check the page by eye.
  Rendering stays well under a second.

## 1.6.0 · 2026-11-22
- Clearer PR comments from `/rk:pr --post`: verdict heading with severity counts, a one-line-per-issue
  table, and folded sections for out-of-diff issues, minor issues, agreed comments and an AI fix prompt.
- Inline comments lead with a severity icon and title, keep evidence folded, and add a copyable
  "Prompt for AI agents". Minor findings no longer post inline.
- A one-click suggestion is offered only when the comment covers the finding's whole line range,
  so GitHub can't apply it to the wrong lines. Code fences survive backticks in the code.

## 1.5.0 · 2026-11-22
- HTML walkthrough v5: the header links the PR and reviewed commit; one facts line (size, estimated
  review time, how findings were checked) replaces the stat grid; a verdict card under the title
  holds the verdict, why, and every finding with its fix and the copy-all prompt; explain mode has
  no warning banner or repeated summary; before and after are side-by-side cards; one files table
  shows reading order, role and size. `evals/build_walkthrough_demo.py` previews the page.

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
