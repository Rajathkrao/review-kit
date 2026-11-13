# Report format

Same structure every time, so reviews are easy to scan and paste. Omit a section only when
the mode never produces it (e.g. no "Existing PR comments" outside pr mode).

```markdown
## Review · <target> · <mode>

**Verdict: Don't ship yet** — <one terse line: the strongest reason, or "no material issues found">
**What this change does:** <two sentences in plain words, for someone new to this code>
**Checked against:** <purpose source, e.g. docs/adr/0007-export-limits.md, or "inferred from commits"> · <n> requirements: ✅ <met> ❌ <missing> ⚠️ <cannot verify>
**Execution:** completed | partial | failed | nothing-to-review · <reviewed commit short SHA> · <seconds or "lenses: …">
**Verification:** <`pytest tests/test_x.py` → 14 passed, 1 failed> | <repro: `python repro/f2.py` → sum 999> | tests not run (<why>)

### Findings

**1. Critical: <title>**
`src/export/service.py:42-47`
<What goes wrong, for whom and when, 2–4 sentences. Say why the code does it: the wrong assumption.>
**Trigger:** <the smallest concrete input or sequence that causes it, with real values>
**Impact:** <what it costs: money, data, security, users affected, and whether it is silent>
**Fix:** <concrete change; short code sketch if it helps>
**Test:** <the test that fails today and passes after the fix, one line>
<sub>confidence 92 · adversarial, correctness · source-verified · M2</sub>

**2. Important: <title>**
...

### Worth a look
- `src/jobs.py:88` <title>: <one line on the risk>. Check: <the one fact that decides it>.

### Spec compliance            (when the contract has items)
- ✅ M1 Only caller's tenant — `service.py:28`
- ❌ M2 Archived invoices excluded — no filter in `service.py:30-36` (→ finding 3)
- ⚠️ M3 413 above 10k rows — not in this diff; check `gateway/limits.yaml`

### Existing PR comments       (pr mode)
| # | Comment (author) | Verdict | Why |
|---|---|---|---|
| 1 | "Use a Set here" (alice) | Valid, unaddressed | O(n²) on 10k rows, line 61 |

### Dismissed
- <title> — <the disproof, with file:line>  (one line each; the reader can overrule)

### Not reported / not checked
<k> minor hidden (`--all`) · Not checked: <lenses not run, tests not run, unreachable services>
```

Rules:

- Length: the report is read, not skimmed past. Each finding is at most ~120 words: the
  description in 2–3 sentences, and Trigger, Impact, Fix and Test one line each (a code sketch
  only when the fix isn't obvious from one line). The whole report stays under ~900 words plus
  findings. Writing it is often the slowest step of a review.
- No findings: write `### Findings` then `No issues found. Checked: <lenses> against <contract>.`
- Omit empty sections (no "Worth a look" header with nothing under it).
- Plain words: short sentences, explain a technical term the first time. The reader may never
  have seen this code. Number findings so the user can say "fix 1 and 3".
- One line of genuine praise is allowed after the verdict line if something is notably well
  done (superpowers: accurate praise builds trust). Never generic praise.
- File references are `path:start-end`. In pr mode also include a GitHub link with the full
  head SHA: `https://github.com/<owner>/<repo>/blob/<sha>/<path>#L<start>-L<end>`, with at least
  one line of context before and after (Anthropic code-review link format).
- Severity labels are the agent-skills prefixes: **Critical:**, **Important:** (agent-skills
  "Required"), **Minor:** / **Nit:**, **FYI**.
- `--all` shows the hidden minors.

## PR comment format (posted with --post)

Inline comment, one per finding located on a line in the PR diff:

```markdown
**Critical:** <title>

<What goes wrong and why, 1–3 sentences.>

**Suggested fix:** <one or two sentences>

```suggestion
<replacement lines, only when the fix is a small, exact replacement of the commented lines>
```

<sub>review-kit · confidence 92 · source-verified</sub>
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
`source-verified` or `test-reproduced`. A test-reproduced
finding includes its command, observed result and exit status. The final JSON
contract and migration rules are in `verification.md`.
