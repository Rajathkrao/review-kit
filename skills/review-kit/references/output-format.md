# Report format

Same structure every time, so reviews are easy to scan and paste. Omit a section only when
the mode never produces it (e.g. no "Existing PR comments" outside pr mode).

```markdown
## Review · <target> · <mode>

**Verdict: Don't ship yet** — <one terse line: the strongest reason, or "no material issues found">
**Checked against:** <contract source, e.g. docs/adr/0007-export-limits.md> · <n> requirements: ✅ <met> ❌ <missing> ⚠️ <cannot verify>
**Execution:** completed | partial | failed | nothing-to-review · reviewed commit: <SHA>
**Verification:** <`npx jest src/export` → 14 passed, 1 failed> | tests not run (<why>)
**Scope:** <n> files, +<a>/−<d> · lenses: <list> · second model: <codex | claude-opus | not used | unavailable: reason>

### Findings

**1. Critical: <title>**
`src/export/service.ts:42-47`
<What goes wrong and why, 1–3 sentences. Name the input or sequence that triggers it.>
**Fix:** <concrete change; short code sketch if it helps>
<sub>confidence 92 · errors, adversarial · verified by test · M2</sub>

**2. Important: <title>**
...

### Spec compliance            (spec / deep with contract / full / pr)
- ✅ M1 Only caller's tenant — `service.ts:28`
- ❌ M2 Archived invoices excluded — no filter in `service.ts:30-36` (→ finding 3)
- ⚠️ M3 413 above 10k rows — enforced in gateway config? Not in this diff; check `gateway/limits.yaml`

### Existing PR comments       (pr mode)
| # | Comment (author) | Verdict | Why |
|---|---|---|---|
| 1 | "Use a Set here" (alice) | Valid, unaddressed | O(n²) on 10k rows, line 61 |
| 2 | "Remove the retry" (bob) | Push back | Retry is idempotent per ADR-0007; removing it drops a stated requirement |

### Not reported
<k> candidates dropped after verification · <m> minor suggestions hidden (`--all` to show)
Declined to judge: <one line each, if any>
Not checked: <lenses that didn't run, unreachable services, tests not run>
```

Rules:

- No findings: write `### Findings` then `No issues found. Checked: <lenses> against <contract>.`
- One line of genuine praise is allowed after the verdict line if something is notably well
  done (superpowers: accurate praise builds trust). Never generic praise.
- File references are `path:start-end`. In pr mode also include a GitHub link with the full
  head SHA: `https://github.com/<owner>/<repo>/blob/<sha>/<path>#L<start>-L<end>`, with at least
  one line of context before and after (Anthropic code-review link format).
- Severity labels are the agent-skills prefixes: **Critical:**, **Important:** (agent-skills
  "Required"), **Minor:** / **Nit:**, **FYI**.
- `--all` adds a `### Lower confidence (60–79)` section and the hidden minors, clearly labeled.

## PR comment format (posted with --post)

Inline comment, one per finding located on a line in the PR diff:

```markdown
**Critical:** <title>

<What goes wrong and why, 1–3 sentences.>

**Suggested fix:** <one or two sentences>

```suggestion
<replacement lines, only when the fix is a small, exact replacement of the commented lines>
```

<sub>review-kit · confidence 92 · verified by test</sub>
```

Review summary body (submitted as event `COMMENT`, never APPROVE or REQUEST_CHANGES unless the
user says so):

```markdown
### Code review (review-kit)

**Verdict:** Ship after fixes — <reason>
**Checked against:** <contract source>
**Verification:** <tests run and result, or "not run">

Found <n> issues (<c> critical, <i> important). Inline comments below.
<Findings whose lines are outside the PR diff, listed here with links.>

<sub>Generated with review-kit for Claude Code. React 👍 / 👎 to tell us if this was useful.</sub>
```

Replies to existing review threads go in the thread
(`gh api repos/{owner}/{repo}/pulls/{pr}/comments/{id}/replies`), not as top-level comments
(superpowers receiving-code-review).

Reports and HTML must display execution state and the reviewed commit/context.
Only completed reviews may say "No issues found" or be submitted to a PR.
For partial/failed/empty-scope runs, say the result is inconclusive and list the
missing checks; never convert missing evidence into approval. Findings display
`source-verified`, `test-reproduced`, or `unverified` labels. A test-reproduced
finding includes its command, observed result and exit status. The final JSON
contract and migration rules are in `verification.md`.
