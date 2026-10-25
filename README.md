# review-kit

Code review for Claude Code that checks a change against **what it was meant to do**, runs focused
reviewers in parallel, tries to **disprove every finding** before showing it, and reports only what
survives. Built from the review rules in addyosmani/agent-skills, obra/superpowers,
openai/codex-plugin-cc and Anthropic's code-review / pr-review-toolkit plugins
(see `skills/review-kit/references/SOURCES.md`).

## Install (2 commands)

Inside Claude Code:

```
/plugin marketplace add Rajathkrao/review-kit
/plugin install rk@review-kit-marketplace
```

Start a new Claude Code session, then try `/rk:quick` in any git repo.

**Update later:** `/plugin marketplace update review-kit-marketplace`
**Remove:** `/plugin uninstall rk@review-kit-marketplace`

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

If `/plugin marketplace add` fails with an SSH error, use the HTTPS URL:
`/plugin marketplace add https://github.com/Rajathkrao/review-kit.git`
</details>

**Requirements:** `git` and `python3` (3.9+). PR mode needs the GitHub CLI logged in (`gh auth login`).
Second-model review uses the Codex CLI if it is installed and logged in
(`npm i -g @openai/codex && codex login`), otherwise a different Claude model. Nothing else to install.

## Quick start

```
/rk:quick                 # fast review of your current branch + uncommitted changes
/rk:deep --html           # full adversarial review + step-by-step HTML walkthrough
/rk:spec                  # review against the ADR / spec / plan for this change
/rk:pr 1234 --post        # review a GitHub PR, judge its comments, post after you approve
```

## Commands

| Command | What it does | Typical time |
|---|---|---|
| `/rk:quick [target]` | One pass, verified, at most 5 findings | 1–3 min |
| `/rk:deep [target]` | Adversarial + correctness + history + errors/tests + security lenses in parallel, then verification | 5–12 min |
| `/rk:spec [target]` | Checks the change against its ADR / spec / plan, requirement by requirement | 3–6 min |
| `/rk:pr <number\|url>` | Deep review of a GitHub PR, judges its existing comments, `--post` to publish | 6–14 min |
| `/rk:test [target]` | Finds the tests that cover the change, asks, runs them, mutation-checks; live checks on request | varies |
| `/rk:arch [target]` | Design, boundaries, contracts, types, and whether the approach is right | 4–8 min |
| `/rk:standards [target]` | Against coding standards and your CLAUDE.md, with concrete simplifications | 3–6 min |
| `/rk:full [target]` | deep + spec + arch + standards, then offers tests | 10–20 min |
| `/rk:review` | Asks which of the above to run | |

**Target**: nothing (current branch vs its base, plus uncommitted work), `main...feature`, a commit,
a PR number or URL, or a path.

**Flags** (any mode): `--html` step-by-step explainer page · `--second-model` independent review by
Codex or another Claude model · `--run` pre-approve running the proposed tests · `--all` also show
lower-confidence and minor findings · `--focus "auth changes"` · `--base develop` · pr mode:
`--post`, `--quick`.

## How it keeps the noise down

1. Every lens writes *candidates*, not findings.
2. A separate verifier re-reads the code for each candidate, tries to disprove it, and scores it with
   Anthropic's 0–100 rubric. Below 80 is dropped (kept in the package with the reason).
3. Pre-existing issues, linter-level nits and style without a written rule are always dropped.
4. Minor findings are hidden by default (except in `standards` mode); 5 findings max in quick mode,
   10 otherwise.
5. Zero findings is a valid result.

## How it finds the purpose

Before reviewing, it looks for an ADR, spec, plan or design doc tied to the change (changed `.md`
files, `docs/adr`, `docs/decisions`, specs/plans mentioned in commits, branch name or PR body). It
shows you the candidates. If there are none, it asks what the change is for. Findings that break a
stated requirement cite it (`M2`).

## Output

A fixed-format report: verdict, what it was checked against, verification evidence, findings with
file:line, fix and confidence, spec compliance per requirement, existing PR comment verdicts, and
what was dropped or not checked. With `--html`, a self-contained page that walks through the change
step by step in execution order with each finding pinned to the step where it happens; saved to
`~/.review-kit/reports/`.

PR comments are posted only with `--post` and only after you approve the exact preview: one review,
event COMMENT, inline comments on diff lines, everything else in the summary.

## Tips

- If superpowers or agent-skills are installed too, use the `/rk:*` commands directly. Their review
  skills answer to generic phrasings such as "review this", while `/rk:*` always runs review-kit.
- Put your team's review rules in CLAUDE.md. The conventions lens enforces only rules that are written down.
- Review packages live in your temp dir (`/tmp/review-kit/...`): diff, contract, candidates, findings,
  test results. They're useful for auditing why something was or wasn't reported.

## Tested

See `evals/RESULTS.md`. On seeded-bug repos it found every planted defect in deep mode, including
one only visible from the ADR, with zero noise findings. On a clean change it reported nothing,
where the built-in `/code-review` reported six findings. Deep reviews cost about $0.40–1.00 and take
1–2.5 minutes; quick reviews about $0.15 and 30 seconds. Re-run the suite with `evals/run_case.sh`
and score with `evals/score.py`.
