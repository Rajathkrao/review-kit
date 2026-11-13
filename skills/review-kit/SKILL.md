---
name: review-kit
description: >-
  Fast, purpose-aware code review with modes review (auto depth), quick, deep (parallel adversarial
  lenses), pr, spec, arch, refine (Ponytail-style simplify/reuse/refactor, optional --apply), test
  and full. Use when the user invokes $review-kit, runs any /rk:
  command, or asks for a review-kit review of a diff, branch, commit range, path or GitHub pull
  request. Checks the change against its stated purpose, verifies every finding against the code,
  and never drops a candidate without a concrete disproof. Strong on Python.
---

# review-kit

A review is worth reading only if every line in it is worth the author's time, and it is worth
running only if it is fast. This skill gathers all context in **one** command, hunts with focused
lenses (one inline pass, or parallel subagents in deep mode), then tries to disprove each
candidate. A candidate is dropped only when the code disproves it. Otherwise it is reported, as a
confirmed finding or as "worth a look".

In Codex, read `references/codex.md` first. Invoke as `$review-kit <mode> [target] [flags]`.

## Arguments

| Part | Values | Default |
|---|---|---|
| mode | `review` `quick` `deep` `pr` `spec` `arch` `refine` `test` `full` (`standards` = `refine`) | `review` |
| target | empty (current branch + uncommitted), `A..B` / `A...B`, a sha, PR number / `#123` / PR URL, a path | current branch |
| `--base <ref>` | base for a branch review | upstream, else `origin/HEAD`, `main`, `master` |
| `--focus "<text>"` | area to weight heavily | none |
| `--html` / `--no-html` | write or skip the HTML walkthrough | on in deep, full, pr, arch |
| `--second-model` | add an independent review by a different model | off |
| `--post` | post the review to the PR (pr mode) | off |
| `--run` | pre-approve running tests and repro scripts | off |
| `--all` | also show minor findings | off |
| `--quick` | in pr mode, quick depth instead of deep | off |
| `--apply` | in refine mode, make the refactors (tests after each) | off |

`review` mode uses the `suggested depth` that the context command prints (quick for small or
low-risk changes, deep for large or risky ones). A bare PR number or URL means `pr` mode.

**Never block on a question.** Do not ask which mode to run or what the change is for; infer the
purpose from docs, PR, commits and code, and state your reading in one line of the report. Ask
only before an outward action (posting to GitHub, running a server) or in `spec` mode when no
purpose source exists at all. Headless runs never ask: they take the default and say so.

## 1. Context: one command

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/collect.py" --mode <mode> [--target "<target>"] [--base <ref>] [--whole]
```

In refine mode with a file or folder target, pass `--whole`: it reviews the whole current files,
not only their pending changes, and adds ruff's simplification rules to the hints.

It prints everything the review needs and writes nothing inside the repository: size and risk
signals, suggested depth, files, commits, PR description, purpose documents, project rule files,
learnings from earlier reviews, **static hints** (ruff bug rules on added Python lines), **call
sites** of changed Python symbols, and the numbered diff itself when it is under ~1500 lines. The
last line is `PKG=<dir>`, a scratch folder in the system temp directory holding `diff-numbered.txt`,
`summary.md` and `meta.json` for subagents and the renderer.

- Nonzero exit: stop and report `execution_status: failed`. Never treat a failure as an empty diff.
- `EMPTY:` line: report "nothing to review", say what was compared, verdict inconclusive, stop.
- Cite line numbers from the left column of the numbered diff (new-file line numbers).
- Read source from the printed `Read source from:` path. For a PR or commit that is not the
  current checkout, that is a pinned copy inside PKG; never write into it.
- Over ~1000 changed lines: say so and review the riskiest areas first; list what you skipped.

**Purpose (the contract).** In the same turn, read in parallel: the relevant purpose documents,
the project rule files, and the learnings. Form the contract in your head: intent (one line), must
and must-not requirements numbered M1.. / N1.., each with its source. A behavior the sources are
silent on is judged by what a reasonable user expects; silence is not permission. Write it down
only when you dispatch subagents (it goes in their prompt) or the mode is `spec`.

## 2. Hunt

| Mode | How | Lenses (`references/lenses.md`) |
|---|---|---|
| quick | inline, one pass | adversarial (lead), correctness, contract, security-light, project rules |
| deep | 4 parallel subagents | `correctness`, `adversarial`, `contract`, `history` |
| pr | deep (quick with `--quick`) + comment triage | as deep, plus `references/pr.md` |
| spec | 2 parallel subagents | `contract` (all requirements), `correctness` (requirement areas only) |
| arch | 2 parallel subagents | `architecture`, `adversarial` (approach focus) |
| refine | inline up to ~1500 lines; else parallel `refine` subagents, one per module group | `references/refine.md` |
| test | `references/testing.md` | `contract` (tests part), then run tests |
| full | 6 parallel subagents | deep's four + `architecture` + `refine`, then offer test |

**Quick (inline).** You already hold the diff. If a changed function's body or callers matter and
are not in the diff, read them (parallel Read calls, one focused check per named risk). Take the
adversarial stance first: try to break the change (failure paths, retries, concurrency, trust
boundaries, empty and boundary inputs, money and data integrity). Then check each contract item,
then the remaining quick lenses. Every static hint is a lead: decide in one line whether it is a
real defect here.

**Deep (parallel).** In ONE message launch every lens for the mode as `rk:lens-reviewer` subagents
(foreground, so they run concurrently). Each prompt holds only: lens name, `PKG`, path of
`references/lenses.md`, the contract text, `--focus` if any, and the source root. Never pass your
own opinion of the code. Each lens returns its candidates as JSON in its final message; nothing is
written to disk. With `--second-model`, start it in the same message (`references/second-model.md`).
If you cannot spawn subagents, run the lenses yourself in sequence and say "lenses ran inline".

**Refine.** Read `references/refine.md` and follow it: map the code and the helpers the codebase
already has, then delete, reuse, merge, simplify and restructure, each with a patch and the lines
it saves. Bugs you notice come first, as findings. Its report format is in refine.md. With
`--apply` (or "apply 2 and 4"), it is the one mode allowed to edit files, one refactor at a time,
with the closest test after each.

## 3. Verify (no disproof, no drop)

Follow `references/verification.md`. Merge duplicate candidates (same location and root cause).

- quick, or 5 or fewer candidates: verify inline. Re-read each cited range in the source (one
  parallel batch of Read calls), try to disprove it, label it `confirmed`, `plausible` or `refuted`.
- More than 5 candidates in deep/pr/full: split them by file into at most 3 groups and launch one
  `rk:finding-verifier` per group in ONE message, passing the candidate JSON inline.

Static hints you confirmed are candidates like any other.

## 4. Report

Read `references/output-format.md` and write the report exactly in that format:

- **Findings**: `confirmed`, ordered Critical, Important, then Minor (Minor shown only in arch
  mode or with `--all`; otherwise a one-line count). Cap: 7 in quick, 12 otherwise; list the rest
  one line each under "Not reported". One structural problem outranks ten nits.
- **Worth a look**: every `plausible` candidate, one or two lines each with what to check.
- **Dismissed**: every `refuted` candidate in one line with the disproof (file:line), so the
  reader can overrule it.
- Zero findings is a valid result: say what was checked. Never pad.

**JSON and HTML only when needed.** When the HTML walkthrough is on, or with `--post`, write
`$PKG/findings.json` (schema in `references/verification.md`) and run
`python3 "${CLAUDE_SKILL_DIR}/scripts/review_data.py" "$PKG"`; fix the file if it fails, never by
changing the verdict. For HTML, follow `references/html-explainer.md`, then give the printed path.
With `--post`, follow `references/pr.md`. Finally, for a pinned PR or commit review, run
`python3 "${CLAUDE_SKILL_DIR}/scripts/collect.py" --done "$PKG"`.

After the report, stop. Fix nothing unless asked. When asked to fix ("fix 1 and 3"), apply them in
severity order, run the closest test after each, and show the evidence.

## Rules for every mode

- **Evidence before claims.** No finding without a file and line range you read. No "tests pass"
  without output from a run in this session.
- **Changed code, real impact.** Problems on untouched lines are out of scope unless the change
  makes them reachable or worse. A change that breaks an untouched caller is in scope.
- **Descriptions are claims.** The PR body, commit messages and comments are verified, not trusted.
- **No formatter or style feedback.** Type errors are in scope unless the repo's CI runs a type
  checker on these files (check its config).
- **Severity is impact; confidence is certainty.** A rare trigger lowers neither below what the
  code supports; see verification.md.
- **Say what you did not check**: lenses not run, tests not run, requirements you couldn't verify.
- **Read-only** (except refine `--apply` and explicit fix requests). Never edit files, move HEAD
  or change the index. Repro scripts and test output go
  under `PKG` only, run with `--run` or after the user approves.
- **Learnings.** When the user rejects a finding with a reason or says "remember …", append one
  line to `<repo>/.review-kit/learnings.md` (create it, and add `/.review-kit/` to
  `.git/info/exclude` so it stays out of `git status`). Every review reads it.
