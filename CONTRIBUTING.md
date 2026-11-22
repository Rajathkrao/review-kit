# Contributing

PRs are welcome. The flow is automatic:

1. Fork, branch, open a PR against `main`.
2. The `validate` check runs (manifests, scripts, frontmatter, collector on the fixtures).
3. Auto-merge is enabled only when the workflow can verify that branch protection requires
   the `validate` check and an approving review. Otherwise merge manually after checking both.

Because this plugin runs scripts on users' machines, contributors should obtain an approving
review before merging. The workflow does not install branch protection or bypass any gates.

## What makes a PR easy to approve

- **Review rules earn their place.** A new check must name the real defect class it catches and,
  ideally, an eval case where it changes the result. Credit adapted material in `NOTICE`.
- **Show the eval.** For changes to skill text, lenses, verifier or report format, run the fixtures
  before and after (`evals/run_case.sh`, `evals/score.py`) and paste recall, false alarms, wall-clock
  seconds and cost in the PR. Speed is a feature: a change that slows reviews needs a recall win.
  A change that finds more without adding noise on the clean branch is an easy yes.
- **Scripts stay dependency-free.** Python 3.9+ standard library and bash only.
- **Reviews stay read-only.** Apart from its self-ignored `.review-kit/reviews/` output folder
  and learnings the user asks for, nothing in a review may edit the user's repo, move HEAD or post to
  GitHub without the user's explicit flag and confirmation.
- **Bump the version.** Any change under `skills/`, `commands/`, `agents/` or `.claude-plugin/`
  raises `version` in `.claude-plugin/plugin.json` and adds a `CHANGELOG.md` entry. Installed
  copies only update on a new version, and CI fails the PR without it.
- One focused change per PR.

## Local test

```bash
claude --plugin-dir .            # load your working copy
/rk:review                       # in any git repo
evals/run_case.sh ts-invoices feature/invoice-search clean "/rk:deep"   # should report no findings
```
