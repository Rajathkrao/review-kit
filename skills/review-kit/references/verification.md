# Verification: disprove before reporting

This stage exists because a reviewer that lists everything is a reviewer people stop
reading. Each candidate must survive an attempt to disprove it.

Sources: Anthropic code-review steps 5–6 (confidence rubric, ≥80 filter, false-positive
list), pr-review-toolkit code-reviewer (confidence ≥ 80), Codex adversarial prompt
(grounding and calibration rules), superpowers task reviewer (severity calibration,
"do not trust the report"), agent-skills doubt-driven-development (RECONCILE classes),
superpowers verification-before-completion (evidence before claims).

## For each candidate

1. **Re-read the code** at `file:line_start-line_end` and enough surrounding code to follow
   the path the candidate describes. Do not rely on the lens's description.
2. **Try to disprove it.** Is there a guard upstream? Does a caller already handle it? Is the
   input actually reachable from an untrusted source? Is this line changed by this diff? Does a
   test already cover it? Does the contract or a code comment explain it as intentional?
3. **Classify** (doubt-driven RECONCILE, first match wins):
   - `contract-misread`: the lens misunderstood the contract → score 0
   - `noise`: correct under context the lens didn't have → score 0, note the context
   - `trade-off`: real but deliberate and documented → score ≤ 50, unless the trade-off breaks a contract item
   - `valid`: real issue → score with the rubric
4. **Use test evidence** if `$PKG/test-results.md` exists. A failing or mutation-surviving test
   that matches the candidate is the strongest evidence there is. Mark `verified_by: "test"`.
   A focused test the user approved may be run now; never a full suite.
5. **Score** with the rubric below and set severity with the calibration below.

## Confidence rubric (Anthropic code-review, verbatim)

- **0**: Not confident at all. This is a false positive that doesn't stand up to light scrutiny, or is a pre-existing issue.
- **25**: Somewhat confident. This might be a real issue, but may also be a false positive. You weren't able to verify that it's a real issue. If the issue is stylistic, it is one that was not explicitly called out in the relevant CLAUDE.md.
- **50**: Moderately confident. You were able to verify this is a real issue, but it might be a nitpick or not happen very often in practice. Relative to the rest of the change, it's not very important.
- **75**: Highly confident. You double checked the issue, and verified that it is very likely a real issue that will be hit in practice. The existing approach is insufficient. The issue is very important and will directly impact the code's functionality, or it is an issue that is directly mentioned in the relevant CLAUDE.md or contract.
- **100**: Absolutely certain. You double checked the issue, and confirmed that it is definitely a real issue that will happen frequently in practice. The evidence directly confirms this.

Scores between anchors are fine. The report keeps ≥ 80.

For `standards` and `conventions` findings, "will be hit in practice" means "a reviewer applying
the written standard would require this change". A standards finding with a concrete remedy that
makes the code measurably simpler can reach 80; a matter of taste cannot.

## Always false positives (score 0)

From Anthropic code-review:
- Pre-existing issues.
- Something that looks like a bug but is not actually a bug.
- Pedantic nitpicks that a senior engineer wouldn't call out.
- Issues a linter, type checker or compiler would catch (missing imports, type errors, formatting).
  Assume CI runs those.
- General code quality issues (test coverage, documentation) unless the contract, CLAUDE.md or the
  active mode (`tests`, `standards`) asks for them.
- Issues called out in CLAUDE.md but explicitly silenced in the code (e.g. a lint-ignore comment).
- Changes in functionality that are clearly intentional and directly related to the broader change.
- Real issues on lines the change did not modify.

From the Codex grounding rules:
- Findings that depend on files, lines, code paths, incidents or runtime behavior that can't be
  shown from the repository or tool output.

## Severity calibration (superpowers + Codex + agent-skills labels)

- **Critical** (blocks merge): security vulnerability, data loss or corruption, broken functionality
  on a main path, tenant-isolation break.
- **Important** (fix before merge): the change cannot be trusted until fixed. Incorrect or fragile
  behavior, a missed contract requirement, swallowed errors, tests that assert nothing or were
  weakened, maintainability damage you'd block a merge over.
- **Minor** (optional): polish, simplification, coverage that could be broader.

A stated rationale in the PR or comments ("kept simple per YAGNI") does not downgrade severity.
Judge the code on its merits.

## Output: `$PKG/findings.json`

```json
{
  "verdict": "dont-ship | ship-after-fixes | ship",
  "summary": "Terse ship/no-ship reasoning, not a neutral recap (Codex). Do not restate the verdict word itself.",
  "findings": [
    {
      "id": "F1",
      "severity": "critical",
      "title": "...",
      "file": "...",
      "line_start": 0,
      "line_end": 0,
      "body": "What goes wrong and why.",
      "evidence": "What you re-read or ran that confirms it.",
      "recommendation": "Concrete fix. Code sketch if short.",
      "confidence": 90,
      "lenses": ["errors", "adversarial"],
      "found_by": "claude | codex | claude-<model>",
      "verified_by": "read | test",
      "contract_ref": "M2",
      "suggestion": "optional: exact replacement for lines line_start..line_end, only when the fix is that small"
    }
  ],
  "dropped": [{"title": "...", "confidence": 40, "reason": "guard at api.ts:12 already rejects empty ids"}],
  "spec_status": [],
  "declined": [],
  "not_checked": []
}
```

Verdict: `dont-ship` if any Critical survives; `ship-after-fixes` if any Important survives;
`ship` otherwise. Use `ship` only if you cannot support any substantive finding (Codex).

Keep every dropped candidate in `dropped` with its reason. The report shows only the count, but
`--all` and the HTML explainer use them, and they make the drop decisions auditable.
