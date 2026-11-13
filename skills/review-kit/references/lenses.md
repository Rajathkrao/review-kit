# Lenses

A lens is a focused reviewer. In deep mode each lens is one `rk:lens-reviewer` subagent; in quick
mode you apply the quick subset yourself in one pass. Every lens starts from `$PKG/summary.md` and
`$PKG/diff-numbered.txt` (left column = new-file line number), plus the contract it was given.

## Shared rules

- Review what this change touched, and what it breaks: a caller of a changed function, a
  consumer of a changed return shape, a migration under existing data. Untouched pre-existing
  problems are out of scope unless the change makes them reachable or worse.
- Every candidate names a file and line range you read and a **minimal trigger**: the concrete
  input or sequence that produces the wrong result. No trigger, no candidate.
- Recall matters as much as precision: a separate verifier will disprove what is wrong, but it
  cannot find what you didn't report. Report a real suspicion with honest confidence rather than
  silently dropping it. Do not pad with style, naming or "consider" items.
- To look outside the diff, name the risk first, then do one focused check (the callers listed in
  the summary, the guard upstream, the test file, the model or migration). Don't crawl.
- Static hints in the summary (ruff bug rules on added lines) are leads. Turn the real ones into
  candidates with the trigger; ignore false ones.
- Python changes: also apply `references/python.md` where your lens touches it.
- Read-only. Never edit files, run tests, or spawn subagents. If one test or repro would settle a
  candidate, say so in `evidence`.

## Candidate output

Return one JSON object as your final message (no file writes):

```json
{
  "lens": "correctness",
  "files_read": ["payouts/service.py", "payouts/store.py"],
  "candidates": [
    {
      "title": "Failed transfer is still marked paid",
      "file": "payouts/service.py", "line_start": 49, "line_end": 53,
      "severity": "critical",
      "trigger": "bank.transfer raises (timeout) for payout 7 → except logs → set_status(7, 'paid')",
      "body": "What goes wrong, why the code does it (the wrong assumption), who is hurt.",
      "evidence": "What you read that shows it (e.g. 'set_status is outside the try at :53').",
      "recommendation": "Concrete fix, short code sketch if it helps.",
      "confidence": 90,
      "contract_ref": "M4"
    }
  ],
  "spec_status": [{"id": "M4", "status": "missing", "evidence": "service.py:53 marks paid after a failure"}],
  "not_checked": ["what you could not check and why"]
}
```

`severity`: `critical` | `important` | `minor`. `spec_status` only from the contract lens.

---

## correctness  (deep; quick)
Does the code do what it claims and what the contract requires, on every path?
- Wrong condition, operator, variable, off-by-one, inverted guard, wrong default.
- Edge inputs: None, empty, zero, negative, max, duplicates, unicode, month-end, DST, leap years.
- Error paths: what happens when each call fails. Swallowed exceptions, catch-log-continue,
  returning a default the caller can't tell from success, broad `except` hiding unrelated bugs,
  cleanup skipped, partial writes left behind, retries that never stop or retry non-idempotent work.
- State: ordering assumptions, stale reads, mutation of shared objects, re-entrancy, resource leaks.
- Performance with a concrete cost only: a query per row, O(n²) on input that can be large,
  unbounded fetch or memory growth, blocking I/O on a hot path.

## adversarial  (deep, arch; leads quick)
Break confidence in the change. Assume it fails in subtle, costly or user-visible ways until the
code says otherwise. Give no credit for intent, partial fixes or likely follow-ups.
Attack surface, most expensive first:
- auth, permissions, tenant isolation, trust boundaries (where does untrusted input enter?)
- money and data: loss, corruption, duplication, irreversible state changes
- retries, partial failure, idempotency, rollback safety, crash between two writes
- concurrency: check-then-act, two workers, overlapping jobs, a webhook retried during processing
- degraded dependencies: timeouts, empty responses, slow or failing services
- version skew, schema drift, migrations under live data, backward compatibility
- security: injection (SQL, shell, template, path traversal), unsafe deserialization, SSRF,
  secrets in code or logs, missing authorization on a new handler, IDOR, open redirect,
  model output reaching eval/SQL/shell/HTML
- observability gaps that would hide the failure
Each candidate answers: what goes wrong, why this path is vulnerable, impact, the fix.
In arch mode also challenge the approach: is this design right for the contract?
Quick mode's security-light check: injection, authorization and secrets only.

## contract  (deep, spec; quick when the contract has items)
Compare the change against every numbered contract item, then the tests, then its callers.
- **Missing**: a requirement skipped, or claimed without being implemented.
- **Misunderstood**: the right feature built the wrong way.
- **Extra**: behavior nobody asked for that adds risk.
- Silence is not permission: judge unstated behavior by what a reasonable user expects.
- A requirement you can't verify from the diff: `cannot_verify` with what to check.
- Tests: new behavior without a test that would fail if it broke (risky logic only: money, auth,
  parsing, data writes, a bug fix); weakened tests (assertions loosened, skipped, expected values
  edited to match new output, mocks that make the test assert nothing).
- Callers and compatibility: for every changed signature, return value, raised exception, default,
  field or error message, read the call sites the summary lists. A caller now broken is a candidate.
  Public API, CLI, config, serialized formats and DB schemas: removal or semantic change without a
  migration or deprecation path is a candidate.
Return `spec_status` for every contract item.

## history  (deep)
Does the change undo something done on purpose, or contradict the project's written rules?
- For each modified file: `git log --oneline -8 -- <file>`, then `git log -L` or `git blame` on the
  modified regions. A removed guard, check or special case that an earlier commit added on
  purpose? Read that commit. A re-introduced bug an earlier commit fixed?
- Project rules: the rule files and learnings listed in the summary (CLAUDE.md, AGENTS.md,
  REVIEW.md, `.review-kit/learnings.md`). Flag a violation only of a rule that is written down;
  quote it. Learnings that say "don't flag X" suppress X for every lens.
- Comments in or near the change: does it violate "must hold the lock", "keep in sync with X"?
  Are comments the diff adds or edits still true?
- If `gh` works: review comments on the last few merged PRs touching these files that also apply here.

## architecture  (arch, full)
Is the structure right, and does it get better or worse?
- New pattern where an existing one fits; feature logic in a shared module; dependencies pointing
  the wrong way; cycles; a near-duplicate of an existing helper (name its path).
- Does a refactor reduce complexity or just move it? Count the concepts a reader must hold.
- Repeated conditionals on the same shape (a missing type or dispatcher); a new conditional
  bolted onto an unrelated flow; orchestration mixed with business logic.
- Type boundaries: `Any`, untyped dicts passed between layers, optional fields or casts hiding an
  invariant; can invalid instances be constructed?
- Public contracts (Hyrum's law): any observable change (error text, ordering, field types) breaks
  someone. Prefer addition over modification. Migration and backward-compatibility plan.
- API red flags: different shapes by condition, inconsistent errors, validation scattered in
  internals, list endpoints without pagination, idempotency done as SELECT-then-INSERT.
Every architecture candidate names the structural remedy and what it deletes or simplifies.
