# Contributing

PRs are welcome. The flow is automatic:

1. Fork, branch, open a PR against `main`.
2. The `validate` check runs (manifests, scripts, frontmatter, collector on the fixtures).
3. Auto-merge is switched on for your PR. It squash-merges by itself as soon as CI is green
   **and** the code owner approves. No need to ping anyone; approvals are usually quick.

Because this plugin runs scripts on every user's machine, every outside change gets one
approval before it ships. Nothing else gates it.

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
