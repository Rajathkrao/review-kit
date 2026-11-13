# Verification: no disproof, no drop

Two failure modes ruin a review. False alarms teach the reader to skim. **Dismissed real bugs
are worse**: the reader trusts the review and ships the bug. So verification is not "keep what
scores high". It sorts each candidate by what the code shows:

| Label | Means | Goes to |
|---|---|---|
| `confirmed` | You traced the trigger to the wrong result in the code (or a repro showed it). | Findings |
| `plausible` | Reachable and not disproven, but one fact you can't see decides it (a caller outside the repo, runtime config, a DB constraint, the deploy topology). | Worth a look |
| `refuted` | You can point at the code, test, doc or contract item that disproves it. | Dismissed (one line, with the disproof) |

**The burden of proof is on dismissal.** "I couldn't confirm it" is `plausible`, never `refuted`.
"It is rare" is never a disproof. "Nothing calls it yet" is not a disproof for a public or new
function: it will be called, and the code is what ships.

## For each candidate

1. **Re-read the code** at the cited lines and enough around them to follow the claimed path:
   the function, its callers when the claim depends on input, the guard the claim says is missing.
   Fix line numbers that are off.
2. **Write the minimal trigger**: the smallest concrete input or sequence that causes it here,
   with real values ("`split_installments(1000, 3)` returns `[333, 333, 333]`, sum 999"; "two
   deliveries of event e1 both pass the existence check during `await ack()`"). If you cannot
   write one, the candidate is `refuted` (say why) or a style opinion (drop it as out of scope).
3. **Try to disprove it**, and name what you checked: an upstream guard or validation, the caller
   that already handles it, a type or schema constraint, a unique index, a lock, a test that
   covers exactly this, the contract or a comment declaring it intended, unchanged pre-existing code.
4. **Settle contested ones cheaply when you can.** For pure logic (arithmetic, parsing, date math,
   string handling, a small class), a 5–15 line repro script is the best evidence. Write it under
   `$PKG/repro/`, run it only with `--run` or after the user approves, never against real
   services, and quote the output. A repro that shows the wrong result makes it `confirmed` with
   `evidence_status: test-reproduced`.
5. **Label, then set severity by impact** (below). Likelihood belongs in the text, not in the label.

## Never a reason to refute

- The trigger is uncommon (month-end, two requests in the same millisecond, a retry after a
  timeout, an empty list, a second worker, a name with an apostrophe). Ordinary production
  events are reachable. Put the trigger in `evidence` and let severity carry likelihood.
- The author's description says it is fine, or the code "looks intentional" without a comment,
  doc or test saying so.
- The input "probably" comes from a trusted source. Trace it, or label `plausible` and say
  which source to check.
- A linter or type checker "would catch it". Only if the repo's CI actually runs that tool on
  this file. Static hints printed by the context command are exactly such catches that CI missed.

Lost or duplicated money, lost or corrupted data, broken auth or tenant isolation, a crash on a
main path, and silent failures are never dropped for being rare.

## Always out of scope (drop silently, not even "Dismissed")

- Formatting, naming taste, and anything the repo's formatter or linter config enforces.
- Pre-existing problems on lines this change didn't touch and doesn't make reachable or worse.
- Pedantic nitpicks a senior engineer wouldn't raise; "consider" suggestions without a defect.
- Missing docs or coverage, unless the contract, project rules or mode asks for them.
- Rules explicitly silenced in the code (a lint-ignore with a reason).
- A `shortcut:` comment that names its limit, unless the expected load already crosses it.
- Framework defaults the change merely inherits (Django admin's delete action and per-field
  editability, default permissions, a library's default timeout already used elsewhere) unless the
  contract or project rules forbid them, or the change makes them newly reachable by untrusted
  users. Report those at most as Minor.

## Severity (impact, not effort)

- **Critical** (blocks merge): security hole, data loss or corruption, lost or duplicated money,
  broken main path, tenant-isolation break.
- **Important** (fix before merge): wrong behavior on a real path, a missed contract requirement,
  swallowed errors, a crash on a reachable input, a caller broken by the change, weakened tests.
- **Minor**: polish, simplification, a narrow edge with small impact. Also log wording and
  observability-only changes, unless something in the repo (a test, parser, alert rule or the
  contract) depends on the old text.

A requirement you inferred yourself (not written in a doc, PR, issue, comment or rule file) never
raises severity on its own: judge the finding by its real impact. A candidate you would score below
70 confidence is `plausible`, whatever its severity.

A finding whose harm depends on something you cannot see (deployment config, a formatter, a
caller outside the repo) is `plausible` with that fact as its `check`, not `confirmed`. A
validation gap in an untouched model is in scope only when the change adds the first path that
writes the bad value *and* nothing else (form, serializer, DB constraint) stops it; otherwise
it is pre-existing.

A stated rationale in the PR ("kept simple") does not lower severity. Judge the code.

## Confidence

0–100, your certainty that the defect is real and reachable, not how often it happens:
`confirmed` is usually 80–100, `plausible` 40–79. Report it; it no longer decides what is hidden.

## `$PKG/findings.json` (only when HTML or posting needs it)

```json
{
  "execution_status": "completed",
  "verdict": "dont-ship | ship-after-fixes | ship",
  "summary": "Terse ship/no-ship reasoning, not a recap.",
  "findings": [
    {
      "id": "F1", "severity": "critical", "title": "...",
      "file": "...", "line_start": 0, "line_end": 0,
      "body": "What goes wrong and why.",
      "evidence": "What you re-read or ran, and the minimal trigger.",
      "recommendation": "Concrete fix.",
      "confidence": 90, "lenses": ["adversarial"],
      "found_by": "claude | codex | claude-<model> | ruff",
      "verified_by": "read | test",
      "evidence_status": "source-verified | test-reproduced",
      "contract_ref": "M2",
      "suggestion": "optional exact replacement for line_start..line_end"
    }
  ],
  "plausible": [{"title": "...", "file": "...", "line_start": 0, "check": "what fact decides it", "confidence": 60}],
  "dropped": [{"title": "...", "reason": "the disproof, with file:line"}],
  "spec_status": [{"id": "M1", "status": "met | missing | misunderstood | cannot_verify", "evidence": "file:line"}],
  "not_checked": []
}
```

Verdict: `dont-ship` if any Critical finding; `ship-after-fixes` if any Important; else `ship`.
`execution_status` is `completed` only if the selected stages ran; `partial` when context, a lens,
a requested test run or the second model was unavailable; `failed` for a failed review;
`nothing-to-review` for an empty diff. Every non-completed status uses `verdict: inconclusive`.
`test-reproduced` needs `test_evidence` with `command`, numeric `exit_code`, `observed`,
`setup_succeeded: true` and `target_exercised: true`.
