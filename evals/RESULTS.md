# Test results (2026-10-24)

All runs used real headless Claude Code 2.1.310 (`claude -p`) with this plugin loaded, against
seeded-bug fixture repos (`fixtures.tgz`). The planted defects are listed in `answer-keys.json`.
The reviewer never sees that file. Control = Claude Code's built-in `/code-review`, same repo,
same branch.

Fixtures:
- **ts-invoices / feature/invoice-export**: TypeScript. 6 planted defects: cross-tenant export via
  `?tenant=`, archived rows not excluded (only detectable from the ADR), row-cap off-by-one, empty
  200 on failure, unbounded retry, weakened test. Also bait: a pre-existing bug in an untouched
  file, a documented ADR trade-off, a style nit.
- **cs-orders / feature/cancel-order**: C#. 5 planted defects: inverted status guard, refund
  before status update (double refund), `catch (Exception)` returning 204, string-built SQL,
  already-cancelled orders not rejected. **Held out**: the skill text was not tuned on this fixture.
- **ts-invoices / feature/invoice-search**: a small, correct change. Any finding is a false alarm.

| Run | Planted defects found | Extra / noise findings | Cost | Time |
|---|---|---|---|---|
| Built-in `/code-review`, TS | 5/6 (missed the ADR-only defect) | 3 (1 real: CSV escaping) | $0.13 | ~20 s |
| `/rk:deep`, TS (v1) | 6/6 | 0 (CSV escaping wrongly declined → rule fixed) | $0.81 | ~1.5 min |
| `/rk:deep --html --second-model`, TS (v3) | 6/6 + CSV escaping | 0 | $1.02 | ~2 min |
| `/rk:quick`, TS | 5 shown + 1 listed as cut by the 5-finding cap | 0 | $0.16 | ~30 s |
| `/rk:pr 42 --post --html`, TS (simulated GitHub) | 6/6; correctly pushed back on a wrong reviewer comment, endorsed a valid one, skipped a resolved one | 0 | $0.81 | ~1.7 min |
| `/rk:test --run`, TS | 5/6; ran tests; mutation check exposed the untested row cap; files restored | 0 | $0.38 | ~1.7 min |
| `/rk:standards`, TS | 3/6 as findings, other 3 listed as unverified (expected: standards mode) | 0 | $0.38 | ~1.3 min |
| Built-in `/code-review`, C# | 5/5 | 4 (speculative DI, coverage, ProblemDetails, typing) | $0.07 | ~20 s |
| `/rk:deep`, C# (held out) | 5/5, twice | 0 | $0.72–0.89 | 1.5–2.3 min |
| `/rk:spec`, C# | 5/5, per-requirement table | 0 | $0.47 | ~1.7 min |
| `/rk:arch`, C# | 5/5 with structural fixes | 0 | $0.45 | ~1.6 min |
| `/rk:full`, C# | 5/5 + CancellationToken + 1 minor test gap | 0 | $0.91 | ~1.8 min |
| Built-in `/code-review`, clean change | n/a | **6** | $0.06 | ~16 s |
| `/rk:deep`, clean change (×2) | n/a | **0** both times | $0.37–0.40 | 35–51 s |
| `/rk:quick`, clean change | n/a | **0** | $0.14 | ~22 s |

## What changed because of testing

| Problem seen | Fix kept |
|---|---|
| Spec lens declined CSV escaping because "the ADR is silent" | Superpowers' "silence is not permission" rule made explicit for `declined` |
| Lenses cited line numbers from inside the diff file | Collector writes `diff-numbered.txt` with new-file line numbers; all stages cite from it |
| Two runs started in the same second shared a package directory | Package directories get a unique suffix |
| Quick mode drifted from the report format and line numbers | Quick mode must read the format file and open each file before citing |
| `/rk-deep` style names didn't resolve headlessly | Plugin renamed to `rk`: `/rk:deep`, `/rk:pr`, … |
| PR mode hesitated to post because a valid existing comment wasn't in its findings | Valid existing comments are endorsed in the summary, never re-posted, never block posting |
| `git fetch` could hang on a credential prompt | `GIT_TERMINAL_PROMPT=0` and a timeout in the collector |

## Not tested here

- Interactive prompts (choosing the purpose doc, approving test commands, approving a post). Headless
  runs exercise the non-interactive fallbacks; the interactive path is the same flow with AskUserQuestion.
- Real Codex: the Codex path was tested with a stub `codex` binary (prompt built from stdin, output
  converted to candidates, "not installed" fallback to a different Claude model). Run `--second-model`
  once with your Codex login to confirm.
- Real GitHub: PR mode ran against a simulated `gh` (`fake-gh`) that serves a PR with review threads
  and records what gets posted. Submit and reply payloads were checked.
- dotnet test execution (no .NET SDK in the test workspace). Test command detection for .NET was checked.
- Large monorepo diffs. The collector warns above ~1000 changed lines and suggests splitting by area.

# Re-test after PR #5 (2026-10-25)

PR #5 made reviews fail closed (#1–#4). Follow-ups: #5 itself was patched so missing PR-comment
context (no GraphQL) no longer blocks a completed review; PR #7 makes the skill always write and
validate `findings.json`, which real-model runs showed was skipped on clean runs and in test mode.

## Reliability: the 22 failure-scenario regression tests (`tests/test_reliability.py`)

| Code | Result |
|---|---|
| Before #5 (158686b) | Mishandles nearly every scenario: bad ranges/bases and failed PR diffs became reviews, malformed findings and Codex prose rendered as "No issues found", posting continued after failed PR lookups (13/13 cases), historical reviews read the dirty checkout. Only the new validator's own checks pass (they didn't exist before). |
| After #5 | 22/22 pass |

## Detection (real headless Claude Code runs, same fixtures as v0.3)

| Case | v0.3 (before) | After #5 + #7 |
|---|---|---|
| `/rk:deep --html`, TS export | 6/6, 0 noise | 6/6, 0 noise |
| `/rk:deep`, C# cancel (held out) | 5/5, 0 noise | 5/5, 0 noise (×2) |
| `/rk:spec`, C# | 5/5 | 5/5 |
| `/rk:test --run`, TS | 5/6 | 6/6 |
| `/rk:quick`, TS | 5 shown + 1 cut by cap | 5/6 |
| `/rk:pr 42 --post --html` (simulated GitHub) | 6/6, posted after confirmation | 6/6, posted by itself, pinned to the reviewed commit |
| `/rk:deep`, clean change | 0 findings | 0 findings |
| `/rk:quick`, clean change | 0 findings | 0 findings |

Detection quality is unchanged, as expected: #5 changed no review criteria.

## Structured output validity (new in #5: `scripts/review_data.py`)

| Case | After #5 only | After #5 + #7 |
|---|---|---|
| deep TS / C#, spec, quick TS, pr | valid | valid |
| deep clean `--html` | no `findings.json` → HTML refused | valid, HTML rendered |
| quick clean `--html` | `[]` (wrong shape) → HTML refused | valid, HTML rendered |
| test `--run` | no `findings.json` | valid |

Cost and time are unchanged: deep $0.38–0.92 / 47–140 s, quick $0.12–0.24 / 19–52 s.
Single run per case; `evals/score.py` is a keyword aid, and every report above was also read by hand.

# Run folders, /rk:resume and cheap source pinning (2026-10-25)

Real headless Claude Code runs with each run stored in `<repo>/.review-kit/runs/`:

| Case | Detection | Result | Source | Repo after |
|---|---|---|---|---|
| `/rk:deep --html`, TS | 6/6, 0 noise | valid findings, report.md + review.html in run folder | live checkout | `git status` clean |
| `/rk:deep`, C# | 5/5, 0 noise | valid, report.md in run folder | live checkout | clean |
| `/rk:deep --html`, clean change | 0 findings | valid, HTML rendered | live checkout | clean |
| `/rk:pr 42 --post --html` from a checkout on `main` (simulated GitHub) | 6/6 | posted 6 inline comments at the PR head | temporary worktree under `.git/review-kit/worktrees`, **removed** at the end | clean, no leftover worktree |
| Session killed after the contract stage, then `/rk:resume` in a new session | 5/5 | same run folder finished, valid | live checkout | clean |
| Run stopped after the lenses, then `/rk:resume` | 5/5 | reused all 6 lens files, ran only the verifier: **$0.28** vs ~$0.82 for a full run | live checkout | clean |

Regression tests: 29/29 (`tests/test_reliability.py` + new `tests/test_runs.py`).
