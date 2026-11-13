# review-kit

Fast code review for Claude Code. It checks a change against **what it was meant to do**, hunts
with adversarial lenses, checks every candidate against the code, and **never drops a candidate
without a concrete disproof**: what can't be confirmed or refuted is shown as "worth a look", and
what it dismisses is listed with the reason so you can overrule it. Strong on Python.

## Install

Inside Claude Code:

```
/plugin marketplace add Rajathkrao/review-kit
/plugin install rk@review-kit-marketplace
```

Start a new session, then run `/rk:review` in any git repo.
**Update:** `/plugin marketplace update review-kit-marketplace` · **Remove:** `/plugin uninstall rk@review-kit-marketplace`

<details><summary>Other ways to install</summary>

```bash
# Try it for one session without installing
git clone https://github.com/Rajathkrao/review-kit.git
claude --plugin-dir ./review-kit

# Install for your whole team: add to the repo's .claude/settings.json
{
  "extraKnownMarketplaces": {
    "review-kit-marketplace": { "source": { "source": "github", "repo": "Rajathkrao/review-kit" } }
  },
  "enabledPlugins": { "rk@review-kit-marketplace": true }
}
```
</details>

**Requirements:** `git` and `python3` (3.9+). Recommended: `ruff` on PATH (`pip install ruff`) for
a sub-second static pass over changed Python lines. PR mode needs `gh auth login`. Second-model
review uses the Codex CLI if installed and logged in, otherwise a different Claude model.

## Commands

| Command | What it does |
|---|---|
| `/rk:review [target]` | **The default.** Picks quick or deep from the size and risk of the change |
| `/rk:quick [target]` | One inline adversarial pass against the change's purpose, every finding checked |
| `/rk:deep [target]` | Four lenses in parallel (correctness, adversarial, contract, history), parallel verification, HTML walkthrough |
| `/rk:pr <number\|url>` | Deep review of a GitHub PR, judges its existing comments, `--post` to publish after you approve |
| `/rk:spec [target]` | Requirement-by-requirement check against the ADR / spec / plan |
| `/rk:arch [target]` | Design, boundaries, contracts, types, and whether the approach is right |
| `/rk:test [target]` | Finds and runs the tests that cover the change (asks first), mutation-checks them |
| `/rk:full [target]` | deep + architecture, then offers tests |

**Target**: nothing (current branch vs its base, plus uncommitted work), `main...feature`, a commit,
a PR number or URL, or a path.
**Flags**: `--html` / `--no-html` · `--second-model` · `--run` (pre-approve tests and repro scripts) ·
`--all` (show minor findings) · `--focus "auth changes"` · `--base develop` · pr mode: `--post`, `--quick`.

## Why it is fast

- **One context call.** `collect.py` prints everything the review needs in one tool result: size,
  risk signals, suggested depth, purpose docs, project rules, learnings, ruff hints, call sites of
  changed Python functions, and the numbered diff. Nothing is written in your repo.
- **No questions.** It never stops to ask which mode or what the change is for. It infers the
  purpose and says what it used.
- **Parallel where it pays.** Quick mode is a single inline pass. Deep mode runs its lenses and its
  verifiers concurrently, and they return results directly instead of writing files.
- **Files only when needed.** `findings.json` and the HTML page are written only when you ask for
  the walkthrough or for PR posting.

## Why it doesn't dismiss real bugs

Every candidate gets one of three labels:

| Label | When | Shown as |
|---|---|---|
| confirmed | the trigger was traced to the wrong result in the code, or a repro showed it | Findings |
| plausible | reachable and not disproven, but one fact outside view decides it | Worth a look |
| refuted | specific code, test or doc disproves it | Dismissed, one line with the disproof |

Rarity is never a disproof ("two webhooks in the same second" is an ordinary production event), and
"nothing calls it yet" is not a disproof for new code. With `--run`, contested pure-logic findings
are settled with a tiny repro script.

## Python depth

`references/python.md` covers what tests and type checkers miss: blocking calls in `async def`,
unreferenced `create_task`, check-then-act across an `await`, mutable defaults, naive vs aware
datetimes, float money and banker's rounding, SQL built with f-strings, N+1 and lazy loading,
transactions around external side effects, Django/SQLAlchemy/FastAPI/Pydantic traps, migrations
under live data, unsafe deserialization, path traversal, and public API breaks. The context
command runs ruff's bug-class rules (B, ASYNC, DTZ, S, BLE, RUF006, …) on added lines only and lists
the callers of every changed function, so a broken caller is caught without crawling the repo.

## Learnings

Tell it "remember: we don't flag print() in scripts" or reject a finding with a reason, and it adds
a line to `<repo>/.review-kit/learnings.md`. Every later review reads that file and obeys it.
Team-wide rules go in `REVIEW.md` or `CLAUDE.md`.

## Output

A fixed-format report: verdict, what the change does in plain words, what it was checked against,
execution and verification evidence, findings (file:line, trigger, impact, fix, test), worth a look,
spec compliance, PR comment verdicts, dismissed candidates with their disproof, and what was not
checked. Findings are numbered, so "fix 1 and 3" works.

The HTML walkthrough (on by default in deep, full, pr and arch) shows your real code in execution
order, with each problem pinned to its line, the sequence of events that triggers it, root cause,
impact, a fix as a diff and a test that fails today. It is self-contained and works offline. It is
written to the scratch folder in your system temp directory and its path is printed.

**Settings:** `.review-kit/config.json` in the repo or `~/.review-kit/config.json`:
`{"html": "auto" | "always" | "flag" | "never"}`.

## Tested

Real headless Claude Code runs on seeded-bug repos, before and after each change, are recorded in
the PR descriptions and `evals/RESULTS.md`. Run them with `evals/run_case.sh`.

```bash
python -m unittest discover -s tests -v   # no network or model needed
```

Python and shell helpers are dependency-free. Tests use temporary repositories and fake CLIs,
including PR posting; they never publish anything.
