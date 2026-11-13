# Review state and transition audit

Scope: runtime scripts, evaluation runners, GitHub workflows, and the rendered viewer.
This is an inventory of the stateful boundaries found in this revision, not a claim that
testing proves every possible execution safe. Review criteria and model prompts are unchanged.

| Boundary | States / transitions | Enforced invariant |
| --- | --- | --- |
| Collection | allocated → collecting → packaged, or failure/interruption | Initial metadata defaults to failed. `packaged` is recorded only after output exists. Temporary-source ownership is saved before later analysis can fail. |
| Run progress | packaged → contract → lenses → optional tests → verified → reported | Reported is terminal. Revisiting an earlier stage invalidates downstream stage markers and cached artifacts. Missing state starts at packaged; corrupt state is rejected. Progress writes use atomic replacement. |
| Completion | artifacts pending → ready → reported | Valid metadata/findings, purpose, mode-specific lens arrays, merge evidence when candidates exist, requested HTML and test disposition are required. PR `--quick` uses quick requirements; a second model cannot replace a required lens. Partial/failed reports remain inconclusive. |
| Source lifetime | live checkout / clean committed checkout / temporary worktree → retained or removed | Resume and completed-report checks validate the source. Live runs bind HEAD, tracked diff, and untracked content with SHA-256. Changed/missing committed source is rejected. HTML falls back to saved diff lines if source no longer matches. |
| Cleanup | active → stale or reported → retained or removed | Unknown/corrupt run state is not deletion authority. Existing keep-source and dirty-worktree protections remain in place. Explicit cleanup can remove clean retained worktrees. |
| Review result | completed / partial / failed / nothing-to-review | Only completed collection supports a completed verdict. Empty and nonempty collected scopes cannot impersonate each other. Existing finding and evidence validation remains in place. |
| PR posting | preview → unchanged payload → eligible open head → submit | Submit requires an existing equal preview payload. Changed findings cannot silently replace approved content. Existing head/state lookup fails closed. Hunk content resembling file headers remains commentable. |
| Second model | unavailable / attempt / retry → validated candidates or failure | A retry must produce a fresh output file. Failed-attempt output cannot be accepted as a successful retry. |
| Evaluations | reserved run → setup → model execution → validated result → completed | Both runners reserve names atomically. Setup/process/result failures remain failed. The adversarial baseline validates the Claude envelope and finding schema instead of manufacturing empty success. |
| Auto-merge | unknown protection → verified gates → head-pinned auto-merge request | Approval or BLOCKED alone is insufficient. The workflow must read required `validate` and approval gates; unavailable/malformed protection fails closed. Ruleset-only configurations are conservatively skipped. |
| Viewer / test proposals / scorer | render/copy/navigation; propose-only; keyword scoring | Viewer controls do not change review status. Test detection proposes commands without execution. Scoring remains explicitly heuristic and cannot certify model accuracy. |

## Compatibility and limits

- Old live-source packages without a fingerprint require a new collection before resuming.
- A completed run is historical evidence. Start a new run to change it.
- For an incomplete run, marking an earlier stage after a later one deletes downstream cached
  findings, reports, HTML, previews and candidate files as appropriate. Save anything needed
  for historical comparison elsewhere before rerunning stages.
- `test-results.md` records executed, unavailable, or declined checks; its existence does not
  prove that tests passed. Source verification and JSON validation do not prove model accuracy.
- Posting still requires user authorization through the skill workflow. Payload equality binds
  the preview to the submission; it does not authenticate a human approval or make network
  retries exactly-once. Check GitHub before retrying a submission with an ambiguous outcome.
- Stage recording is serialized by the orchestrator. Atomic replacement prevents truncated
  JSON; it is not a lock for two orchestrators mutating the same run concurrently.
- Source fingerprints detect changes at validation boundaries, not an external editor changing
  a file immediately after a check. Avoid editing source during a review.
- The auto-merge workflow intentionally skips when it cannot verify branch protection with
  its token. It does not change repository protection or bypass required reviews/checks.

## Regression coverage

`tests/test_state_machines.py` exercises malformed metadata/state/lenses, terminal and upstream
stage transitions, source drift, custom output folders, renderer source fallback, result-state
contradictions, preview/submission changes, header-like hunk content, stale retry output,
evaluation failure transitions and protection-gated merging. Existing tests retain coverage
of dirty/retained worktrees, committed context, posting eligibility and HTML escaping.

Run `python -m unittest discover -s tests -v`, `python tests/check_frontmatter.py`,
Python compilation and `bash -n` on all three shell runners. These tests use temporary
repositories and fake model/GitHub CLIs; they do not measure live-model recall or precision.
