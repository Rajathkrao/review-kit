# Contributing

PRs are welcome. The flow is automatic:

1. Fork, branch, open a PR against `main`.
2. The `validate` check runs (manifests, scripts, frontmatter, collector on the fixtures).
3. Auto-merge is enabled only when the workflow can verify that branch protection requires
   the `validate` check and an approving review. Otherwise merge manually after checking both.

Because this plugin runs scripts on users' machines, contributors should obtain an approving
review before merging. The workflow does not install branch protection or bypass any gates.

## What makes a PR easy to approve

- **Review rules come from a source.** New review criteria must trace to one of the four source
  projects listed in `skills/review-kit/references/SOURCES.md`. Add the mapping there.
- **Show the eval.** For changes to skill text, lenses, verifier or report format, run the fixtures
  before and after (`evals/run_case.sh`, `evals/score.py`) and paste recall / false alarms in the PR.
  A change that finds more without adding noise on the clean branch is an easy yes.
- **Scripts stay dependency-free.** Python 3.9+ standard library and bash only.
- **Reviews stay read-only.** Nothing in a review may edit the user's repo, move HEAD or post to
  GitHub without the user's explicit flag and confirmation.
- One focused change per PR.

## Local test

```bash
claude --plugin-dir .            # load your working copy
/rk:quick                        # in any git repo
evals/run_case.sh ts-invoices feature/invoice-search clean "/rk:deep"   # should report no findings
```
