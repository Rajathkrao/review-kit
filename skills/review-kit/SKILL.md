---
name: review-kit
description: >-
  Purpose-aware code review engine with modes quick, deep (adversarial), spec, pr, test, arch, standards and full. Use when the user invokes $review-kit or runs any /rk: command or asks for a review-kit review of a diff, branch, commit range, path or GitHub pull request. Checks the change against its stated purpose (ADR, spec, plan, PR description), verifies every finding before reporting, and reports only what survives.
---

# review-kit

## Codex invocation

When running in Codex, read `references/codex.md` before the pipeline. Invoke as
`$review-kit <mode> [target] [flags]`; Claude Code keeps its `/rk:*` commands.
Use the same review criteria, candidates, verifier, filters and report format.

A review is only useful if every line in it is worth the author's time. This skill
finds candidate issues with focused lenses, then tries to **disprove** each one
before it reaches the report. What can't be defended from the code is dropped.

Every rule in this skill and its references comes from one of four sources:
addyosmani/agent-skills, obra/superpowers, openai/codex-plugin-cc, or Anthropic's
claude-plugins-official (code-review, pr-review-toolkit). `references/SOURCES.md`
maps each rule to its origin. Do not add review criteria that are not in these files.

## Arguments

Parse `$ARGUMENTS` (or the text the command passed you) into:

| Part | Values | Default |
|---|---|---|
| mode | `quick` `deep` `spec` `pr` `test` `arch` `standards` `full` | ask (see below) |
| target | empty (current branch + uncommitted), `A..B` / `A...B` range, commit sha, PR number / `#123` / PR URL, a path | current branch |
| `--base <ref>` | base for branch review | upstream, else `main`/`master` |
| `--focus "<text>"` | area to weight heavily | none |
| `--html` / `--no-html` | write or skip the HTML walkthrough | on in deep, full, pr, arch; off otherwise |
| `--second-model` | add an independent review by a different model | off |
| `--post` | post the review to the PR (pr mode, after confirmation) | off |
| `--run` | pre-approves running the proposed test commands | off (ask first) |
| `--all` | also show findings scored 60–79 and hidden minors | off |
| `--quick` | in pr mode, use quick depth instead of deep | off |

If no mode is given, ask once with AskUserQuestion: Quick (Recommended for small
diffs), Deep, Against spec, Full. A bare number or PR URL as the only argument
means `pr` mode.

**Interactive vs not.** If AskUserQuestion is unavailable (headless `-p`, CI,
scheduled run) never wait for input: take the most reasonable choice, state it in
one line at the top of the report, and never run tests, start servers or post to
GitHub unless the matching flag (`--run`, `--post`) was passed.

## The pipeline

Run these stages in order. Create a task list for every mode except `quick`.

### 1. Package the change

Run the collector. It writes everything later stages read into one directory, so
subagents read files instead of re-deriving the diff:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/collect.py" --mode <mode> --target "<target>" [--base <ref>]
```

It prints the package path (call it `$PKG`): the run folder
`<repo>/.review-kit/runs/<date>-<mode>-<target>/`. Git ignores it (via `.git/info/exclude`)
and it never appears in a reviewed diff. Everything the run produces goes in this folder,
so a later session or another agent can pick the run up from disk.

**Record progress** after each stage, so `/rk:resume` knows where to continue:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/state.py" "$PKG" <stage> [--note "<one line>"]
```

Stages: `packaged` (the collector records it), `contract`, `lenses`, `tests`, `verified`,
`reported`. Right after packaging, store the original arguments:
`state.py "$PKG" packaged --args "<the arguments you were given>"`.

Read `$PKG/summary.md` first. It
holds the stat, file list, commits, size verdict, and purpose-doc candidates. The
full diff is `$PKG/diff.patch`; `$PKG/diff-numbered.txt` is the same diff with
new-file line numbers, and every citation uses those numbers. In PR mode the PR body, review comments and
reviews are in `$PKG/pr.json` and `$PKG/pr-comments.json`.

If collection fails, stop with `execution_status: failed`; never interpret the failure
as an empty diff. If collection succeeds with an empty diff, report
`execution_status: nothing-to-review`, `verdict: inconclusive`, say what was
compared, and stop. If `meta.comment_context_status` is `partial` (PR comments could
not be fully read, e.g. no GraphQL access), the code review still completes: report
the existing-comment triage as incomplete and list the warnings under "Not checked". Do not reuse a nonempty `--out` package.

**Read source from `meta.repo_root`**, never by assuming the current checkout:
- `working-tree`: branch/uncommitted review of the live checkout. Rerun if the user changes it mid-review.
- `checkout-at-reviewed-commit`: the checkout already sits, clean, at `meta.reviewed_commit`, so it is used directly.
- `pinned-worktree`: a temporary detached worktree at `meta.reviewed_commit` under
  `.git/review-kit/worktrees/`. The user's checkout is untouched. Marking the run `reported`
  removes it, so don't remove it yourself and don't write into it.
If the size verdict is `too-large` (over ~1000 changed lines), say so, and suggest
reviewing by directory group (agent-skills change sizing). Continue only if the
user agrees or the run is non-interactive.

### 2. Establish the purpose (the contract)

Follow `references/intake.md`. In short: a change is reviewed against what it was
meant to do. Look for an ADR, spec, plan, design note, README section or PR/issue
description that explains this change. Show the candidates and ask which apply.
If none exist, **ask the user what the change is for**. If they decline or the
run is non-interactive, review against the PR description or commit messages and
say so.

Write the result to `$PKG/contract.md`: intent (1–3 lines), must-do requirements,
must-not constraints, and the source of each. Lenses receive the contract, never
your conclusions about whether the code meets it.

### 3. Run the lenses for the mode

| Mode | Lenses (see `references/lenses.md`) | How |
|---|---|---|
| quick | adversarial (lead), spec (if the contract has requirements), correctness, errors, security-light, conventions | Inline, one pass, no subagents |
| deep | correctness+perf, adversarial, history+conventions, errors+tests, security, spec (if contract has requirements) | Parallel subagents |
| spec | spec, correctness (requirement areas only) | Parallel subagents |
| arch | architecture, adversarial (approach focus) | Parallel subagents |
| standards | standards, conventions | Parallel subagents |
| test | tests, then the test runner flow | `references/testing.md` |
| pr | deep (or quick with `--quick`), plus existing-comment triage | `references/pr.md` |
| full | deep + spec + arch + standards, then offer test | Parallel subagents |

**Dispatching lens subagents.** Launch all lenses for the mode in one message,
each as `rk:lens-reviewer` (run_in_background: false). Each prompt
contains only: the lens name, `$PKG` path, the path to `references/lenses.md`
plus the lens section to apply, the contract path, the `--focus` text if any, and
the output path `$PKG/candidates/<lens>.json`. Do not pass your own opinions of
the code. Lenses are read-only and do not spawn subagents.

If the Agent tool is unavailable (you are already a subagent), run the lenses
yourself one at a time, keep each lens's notes separate, and note "lenses ran
sequentially" in the report.

**Second model.** With `--second-model`, start it in parallel with the lenses
(`references/second-model.md`). Codex if installed and logged in, otherwise a
different Claude model. Always say which one ran or why it didn't. Never skip silently.

### 4. Tests and live checks (when the mode calls for it)

`test` and `full` modes, and any mode where a lens marked a finding
`needs_test: true`, go through `references/testing.md`: propose the exact commands
with `scripts/detect_tests.py`, ask before running (unless `--run`), run, and
save output to `$PKG/test-results.md`. UI live checks hand off to the user's
Playwright CLI skill. Backend live checks propose starting the server and a
throwaway probe script in `$PKG/probes/`.

### 5. Verify every candidate

Merge `$PKG/candidates/*.json` (and second-model findings) into
`$PKG/candidates-merged.json`, collapsing duplicates that point at the same
location and failure. Then dispatch one `rk:finding-verifier` subagent
with `$PKG`, the merged file, `references/verification.md`, and the test results
path if tests ran. It re-reads the code for every candidate, tries to disprove it,
scores it 0–100 with the rubric, sets severity, and writes `$PKG/findings.json`.

**`$PKG/findings.json` is required in every mode and every outcome**, including zero
candidates, `test` mode, and runs where you skip the verifier. It is always a JSON
object in the shape defined in `references/verification.md`, never a bare list.
When no candidate survives (or none was raised), write it yourself:

```json
{"execution_status": "completed", "verdict": "ship",
 "summary": "<what was checked and why nothing material was found>",
 "findings": [], "dropped": [], "not_checked": ["<anything not run>"]}
```

Every finding you keep needs `evidence` and `evidence_status` (`source-verified` after
you reread the code, `test-reproduced` only with `test_evidence`).

In `quick` mode, review from the adversarial stance first: read the `adversarial` section of
`references/lenses.md` and try to break the change (attack surface, failure paths, retries,
concurrency, trust boundaries), then check each contract requirement, then the remaining quick
lenses. Then apply `references/verification.md` yourself, inline, before
writing anything: open the file at each finding's location (Read), confirm the
problem is there, and take the line numbers from the file, never from
`diff.patch`. Write `$PKG/findings.json` too, so `--html` and PR posting work
the same way in every mode.

### 6. Filter and rank

From `$PKG/findings.json`:

- Keep confidence ≥ 80. Everything below is dropped (shown only with `--all` if 60–79).
- Order: Critical, then Important, then Minor. Within a level, correctness and security first.
- Default report shows Critical and Important. Minor is shown in `standards` mode,
  or with `--all`. Otherwise give a one-line count of hidden minors.
- Cap: 7 findings in quick, 10 otherwise. If more survive, keep the highest
  leverage ones and say how many were cut. One structural problem outranks ten nits.
- Never pad. Zero findings is a valid, useful result: say "No issues found" and what was checked.

### 7. Report

Before writing the report, always run:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/review_data.py" "$PKG"
```

If it fails, fix `findings.json` so it truthfully describes the review (missing fields,
wrong shape, a verdict that doesn't follow from the findings) and run it again. Never
change the verdict or drop a finding just to make validation pass; if the review
really is incomplete, mark it `partial` with verdict `inconclusive`. The report's
verdict and **Execution** line must match the validated file.
Read `references/output-format.md` and write the report in exactly that format,
in every mode including quick. It always starts with a one-line verdict (ship /
ship after fixes / don't ship yet), what the change was checked against, and what
verification evidence exists. Findings cut by the cap are listed one line each
under "Not reported" so nothing verified is lost.

Save the final report text to `$PKG/report.md` (exactly what you show the user) and end
the report with the run folder path. Then mark the run done, which also removes a
temporary source worktree:
`python3 "${CLAUDE_SKILL_DIR}/scripts/state.py" "$PKG" reported`.
Do this after the HTML and any posting below.

- **HTML walkthrough**: follow the `HTML walkthrough:` line in `summary.md` (it already applies
  the mode and config); `--html` turns it on and `--no-html` off, except that config `never` wins.
  When on, read `references/html-explainer.md`, write `$PKG/explainer.json` with a full
  walkthrough and an in-depth entry for **every** reported finding, then run
  `python3 "${CLAUDE_SKILL_DIR}/scripts/render_html.py" "$PKG"` and give the user the printed path.
- `pr` mode with `--post`: follow the posting steps in `references/pr.md`. Show
  the exact comments first and get a yes before anything is posted.

After the report, stop. Don't start fixing anything unless the user asks. When
they ask, apply the fixes in the order Critical → Important, test each, and
report evidence (superpowers verification-before-completion).

## Rules that apply in every mode

- **No shortcuts by diff size.** `deep`, `full`, `pr`, `arch`, `spec`, `standards` and `test` always
  run their lenses as `rk:lens-reviewer` subagents and the `rk:finding-verifier`, and write the HTML
  walkthrough when it is on, however small the change. A small diff makes those steps fast, not
  optional. Inline single-pass review is what `quick` mode is for. `state.py "$PKG" reported`
  refuses to finish a run whose required outputs are missing and lists what to do.

- **Evidence before claims.** No finding without a file and line range you read.
  No "tests pass" without output from a run in this session.
- **Changed code only.** Pre-existing problems on lines the change didn't touch are
  out of scope unless the change makes them reachable or worse.
- **Don't trust descriptions.** The PR body, commit messages and comments are
  claims. Verify them against the diff.
- **No style feedback that a linter, formatter or compiler would catch.** CI runs those.
- **Severity is about impact, not effort.** Not everything is Critical.
- **Say what you did not check.** Lenses that didn't run, tests not run, requirements
  that can't be verified from the diff (⚠️) all appear in the report.
- **Read-only.** Reviews never edit files, move HEAD or change the index. Test runs
  and probe scripts write only to the run folder, a disposable copy, or build/test output folders.

## Resuming a run

`/rk:resume` (or "continue the last review") picks up an interrupted run, including one
started by another session or agent:

1. `python3 "${CLAUDE_SKILL_DIR}/scripts/state.py" --list .` lists runs, newest first, with
   their original args, the stages done and the next stage. Use the run the user names, else
   the newest one that isn't complete. If the newest is complete, show its `report.md` and
   ask whether to start a new run instead.
2. Read `state.json` (mode and args), `meta.json`, `summary.md`, and `contract.md` if present.
   Run `python3 "${CLAUDE_SKILL_DIR}/scripts/state.py" --check-source "$PKG"` before
   reusing any candidates or findings. If it fails (missing source, changed commit, or local
   edits in committed context), start a fresh run; do not reuse the old results.
3. Continue from `next`. Reuse what is on disk: a lens whose `candidates/<lens>.json` exists
   doesn't run again; a valid `findings.json` means verification is done. For a
   `working-tree` run, if `git rev-parse HEAD` no longer matches `meta.reviewed_commit` or the
   diff changed, say so and offer a fresh run instead.
4. Keep recording stages, and finish exactly as section 7 says.
