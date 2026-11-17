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

**Requirements:** `git` and `python3` (the helper scripts use only the standard library and target
3.9+; CI runs them on 3.12). Recommended: `ruff` on PATH (`pip install ruff`) for a fast static
pass over added Python lines; without it the review still runs and says ruff is missing. PR mode
needs `gh auth login`. Second-model review uses the Codex CLI if installed and logged in,
otherwise a different Claude model.

## Commands

| Command | What it does |
|---|---|
| `/rk:review [target]` | **The default.** Picks quick or deep from the size and risk of the change |
| `/rk:quick [target]` | One inline adversarial pass against the change's purpose, every finding checked |
| `/rk:deep [target]` | Four lenses in parallel (correctness, adversarial, contract, history), parallel verification, HTML walkthrough |
| `/rk:pr <number\|url>` | Deep review of a GitHub PR, judges its existing comments, `--post` to publish after you approve |
| `/rk:spec [target]` | Requirement-by-requirement check against the ADR / spec / plan |
| `/rk:arch [target]` | Design, boundaries, contracts, types, and whether the approach is right |
| `/rk:refine [file\|folder\|target]` | Make code smaller and easier to change. Up to three structural moves that each remove several problems, then line-level refactors (delete, reuse, stdlib, merge copies, flatten logic) with patches and lines saved. Measured before and after; `--apply` makes the edits and tests each step |
| `/rk:explain [file\|folder\|target]` | Understand code: an HTML page with architecture and sequence diagrams, a Python module map, reading order and a step-by-step tour. No bug hunt |
| `/rk:test [target]` | Finds and runs the tests that cover the change (asks first), mutation-checks them |
| `/rk:fix [numbers]` | Applies the findings you pick (default: every Critical and Important): failing test first, smallest fix, closest tests run, reverted if it breaks something |
| `/rk:full [target]` | deep + architecture + refine, then offers tests |
| `/rk:standards` | Old name, kept as an alias of `/rk:refine` |

`/rk:review` also takes a mode as its first word (`/rk:review deep`), and a bare PR number or URL
means pr mode.

**Target**: nothing (current branch vs its base, plus uncommitted work), `main...feature`, a commit,
a PR number or URL, or a path.
**Flags**: `--html` / `--no-html` · `--second-model` · `--run` (pre-approve tests and repro scripts) ·
`--all` (show minor findings) · `--open` · `--html-out <dir>` · `--focus "auth changes"` · `--base develop` · pr mode: `--post`, `--quick` · refine: `--apply`, `--for "next change"`, `--comments`, `--tests`.

## Why it is fast

- **One context call.** `collect.py` prints everything the review needs in one tool result: size,
  risk signals, suggested depth, purpose docs, project rules, learnings, ruff hints, call sites of
  changed Python functions, and the numbered diff (inline up to about 1,500 lines; larger diffs
  are read from a scratch folder, riskiest areas first, and the report lists what was skipped).
  The command writes nothing in your repo.
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

## Refine mode

`/rk:refine payouts/` reads the whole folder (or a file, branch or PR) the way a lazy senior
developer would, at two levels in one pass and without asking anything first.

**It starts from measurements, not impressions.** The context command prints a structure map
(`scripts/refine_map.py`, standard library only; under a second on this repo's own 3,100 lines of
scripts, not yet timed on a large codebase): a scoreboard (code lines, functions, longest
function, nesting, special cases), every special case (a branch for one value, a swallowed
exception, a sleep, a flag parameter, a skipped test, a type switch, a workaround comment),
pass-through wrappers, base classes with one subclass, copied function bodies, literals repeated
across files, names nothing else mentions, who imports whom, import cycles, which files keep
changing, and which files change together in git without importing each other. The map reads
Python through `ast`; other languages get line counts and git history only.

**Moves, then refactors.** Three tests turn those leads into problems: what changes together but
lives apart, what is tied together but changes apart, and what survives being deleted. It then
asks what one change would make several problems disappear (a table instead of scattered
branches, one owner for a rule that lives in three places) and reports at most three such
*moves*, each with what it removes, a before/after sketch, safe steps, the tests that pin it and
a strength (Strong or Worth exploring; weaker ideas are not shown). Below them come the
line-level refactors: what can be deleted, which helper the codebase already has, what the
standard library already does, which abstraction has one implementation, which near-copies
should merge. Each has a patch, the lines it saves and why behavior stays the same (callers
checked). Bugs it notices come first.

**`--apply`** (or "apply 2 and 4") runs the covering tests first as a baseline, writes a small
test that pins today's behavior where a move touches untested code, makes the edits one step at a
time with the closest test after each (reverting what breaks), then prints the scoreboard before
and after and looks once more for what the moves exposed.

**Flags.** `--for "add a third payment provider"` ranks everything by how much it eases the change
you are about to make; without it, code that changes often ranks first. `--comments` also removes
comments that only repeat the code. `--tests` also flags tests that cannot fail or only mirror
the implementation. These three flags are written into the skill's instructions but have not
been run end to end yet, so treat them as new. Tell it a structure stays, with a reason, and it is remembered in
`.review-kit/learnings.md` and not proposed again.

Line-level checklist inspired by [Ponytail](https://github.com/DietrichGebert/ponytail). The
structural half was shaped by comparing against the untangle-codebase skill and Matt Pocock's
improve-codebase-architecture skill (ideas only, no text).

## Learnings

Tell it "remember: we don't flag print() in scripts" or reject a finding with a reason, and it adds
a line to `<repo>/.review-kit/learnings.md`. Every later review reads that file and obeys it.
Team-wide rules go in `REVIEW.md` or `CLAUDE.md`.

## Output

A fixed-format report: verdict, what the change does in plain words, what it was checked against,
execution and verification evidence, findings (file:line, trigger, impact, fix, test), worth a look,
spec compliance, PR comment verdicts, dismissed candidates with their disproof, and what was not
checked. Findings are numbered, so "fix 1 and 3" works.

The HTML walkthrough (on by default in deep, full, pr, arch and explain) opens with **problems at
a glance**: every finding in one table with its one-line fix, severity filters, and a "Copy all fix
prompts" button whose text you can paste straight into Claude Code (each problem has its own
"Copy fix prompt" too). Problems fold and unfold, `j` / `k` jump between them, the side menu
follows your scroll, and there is a light/dark switch. Then comes **the big
picture**: an architecture diagram of the parts the change touches (changed parts highlighted,
problem badges linked to the finding), sequence diagrams of the main flow or the failing race, and,
for Python, a module map drawn from the imports so you see the blast radius. Then a suggested
reading order (foundations first), a review-effort score, and your real code in execution
order, with each problem pinned to its line, the sequence of events that triggers it, root cause,
impact, a fix as a diff and a test that fails today. It is self-contained and works offline. It is
written to the scratch folder in your system temp directory and its path is printed.

**Settings:** `.review-kit/config.json` in the repo or `~/.review-kit/config.json`:
`{"html": "always" | "never", "open": true, "html_dir": "~/reviews"}`. Leave `html` out for the
default (on in the modes above, or with `--html`). `open`
launches the page in your browser as soon as it is written (`--open` does it once); `html_dir`
keeps a copy of every page in a folder of your choice (`--html-out <dir>` for one run).

## Tested

Results of real headless Claude Code runs, with seconds and cost, are in `evals/RESULTS.md`.
They are mostly single runs, so read them as a record, not a benchmark.

- **Original set** (`evals/fixtures.tgz`): five small seeded-bug branches in TypeScript, C# and
  Angular. Quick and deep both find every planted bug, so it no longer tells versions apart.
- **Harder Python set** (`evals/hard/`, described in its README): nine branches across five
  small apps, with 28 planted bugs on five of them, four clean branches to catch false alarms,
  and one diff of about 1,240 lines. Latest runs (2026-11-13/14): quick and deep each found
  28/28 with no confirmed findings on the clean branches; quick took about 55 s and $0.40 per
  case, deep (`--no-html`) 1,540 s and $15.02 for the whole set.
- **Refine** (`evals/build_refine_fixture.py` builds a small package with planted problems): one
  report run in 82 s for $0.46, and one `--apply --run` in 106 s for $0.64 that took the package
  from 103 to 48 code lines with its tests passing.

Not run end to end yet: `--post` against real GitHub (covered by unit tests with a fake `gh`),
`--second-model` with a real Codex login (tested with a stub), refine's `--for`, `--comments` and
`--tests`, and refine on a large codebase or on non-Python code.

```bash
evals/run_case.sh py-shop feature/coupon-redemption my-run "/rk:quick"   # one case
JOBS=8 evals/run_hard.sh my-tag "/rk:quick"                              # the whole harder set
evals/score.py --suite my-tag                                            # rescore it
python -m unittest discover -s tests -v                                  # unit tests, no network or model
```

The eval scripts need the `claude` CLI, run it with `--dangerously-skip-permissions` on throwaway
fixture repos, and spend real usage. Runs land in `evals/runs/`. The
unit tests use temporary repositories and fake CLIs, including PR posting, and never publish
anything. The helper scripts are dependency-free; only the frontmatter check in CI needs PyYAML
(`tests/requirements.txt`).
