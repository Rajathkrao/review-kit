# Intake: scope and purpose

## Scope

`scripts/collect.py` resolves the target:

| Target given | What is reviewed |
|---|---|
| nothing | commits on the current branch ahead of its upstream (or merge-base with `--base`, else `main`/`master`), plus staged, unstaged and untracked changes |
| `A..B`, `A...B`, a sha | that range / commit |
| `123`, `#123`, PR URL | the GitHub PR via `gh` (diff, body, linked issues, review threads) |
| a path | the changes under that path; if there are none, the current contents of that path (review as new code) |

The package keeps 10 lines of diff context so lenses rarely need to open whole
files. Lenses still read outside the diff when a named risk needs it (superpowers
task reviewer: one focused check per named risk, such as call sites of a changed
contract).

## Purpose: find what the code is supposed to do

A diff can only be judged against its intent (agent-skills: "Before looking at
code, understand the intent"; superpowers: review "against its plan or
requirements"). The collector lists candidate purpose documents in
`summary.md`, ranked:

1. Markdown files changed in the diff itself (ADRs, specs, plans, READMEs)
2. ADR / decision folders (`docs/adr`, `docs/decisions`, `adr/`, `Documentation/Decisions`, `.adr-dir`) with entries touching the same area or mentioned in commits
3. Spec / plan / design files (`*spec*.md`, `*plan*.md`, `*design*.md`, `docs/superpowers/**`, `specs/**`) mentioned in commit messages, branch name or PR body
4. PR body and linked issues (pr mode)
5. Commit messages (weakest; describes what was done, not what was needed)

### Ask, don't guess

Interactive runs:

- Candidates found: AskUserQuestion with up to 3 candidates (multiSelect) plus
  "None of these". Short label = file name; description = its title line.
- Nothing found, or user picked none: ask once in plain text:
  "What is this change meant to do? A sentence is enough, or point me at a doc/ticket."
- The user can always skip. Then use the PR description or commits and mark the
  contract source as "inferred from commits/PR". Spec-compliance results are then
  reported as low-authority.

Non-interactive: use the top-ranked document if it plainly matches the changed
area, else commits/PR body. State the choice in the report's first lines.

### Write the contract

`$PKG/contract.md`:

```markdown
# Contract
Source: docs/adr/0007-export-limits.md (+ PR #412 body)

## Intent
Users can export their tenant's invoices as CSV.

## Must
- M1: Only invoices from the caller's tenant (ADR-0007 §Decision)
- M2: Archived invoices are excluded
- M3: Max 10,000 rows; larger requests get 413

## Must not
- N1: No change to the existing /invoices list endpoint contract

## Out of scope (stated)
- PDF export
```

Copy requirement wording from the source as closely as possible; number them so
findings can cite `M2`. Do not add requirements the source doesn't state. Behavior
the source is silent on is judged by what a reasonable user would expect, not
treated as permission (superpowers: "the spec is a vision document").
