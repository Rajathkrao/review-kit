# Lenses

Each lens is a focused reviewer. A lens reads `$PKG/summary.md`,
`$PKG/diff-numbered.txt` (diff with new-file line numbers) and `$PKG/contract.md`, applies only its section below, and
writes candidates to `$PKG/candidates/<lens>.json` in the schema at the end.

Shared lens rules (Anthropic code-review, Codex adversarial prompt, superpowers task reviewer):

- Review only what this change touched. A real issue on an unmodified line is out of scope
  unless the change makes it reachable or worse.
- Every candidate must be defensible from code you read. Do not invent files, lines,
  code paths, incidents or runtime behavior. If a conclusion depends on an inference,
  say so in `body` and set `confidence` honestly.
- Prefer one strong finding over several weak ones. Do not dilute serious issues with filler.
- No style, naming or formatting feedback, and nothing a linter, type checker or compiler
  would catch, unless your lens is `standards` or `conventions` and the rule is written down.
- To check outside the diff, name the risk first, then do one focused check for it
  (e.g. read the call sites of a function whose contract changed). Do not crawl.
- Read-only. Do not edit files, move HEAD, or spawn subagents.
- If a candidate could be confirmed by running one specific test, set `needs_test: true`
  and put the exact command in `evidence`. Do not run it.

---

## correctness  (deep, quick, spec)
Sources: agent-skills five-axis (Correctness), Anthropic code-review agent #2 (bug scan).

Does the code do what it claims and what the contract requires?
- Off-by-one, inverted or wrong boolean conditions, wrong operator, wrong variable.
- Edge cases: null/undefined, empty collections, zero, negative, max values, boundaries.
- Error paths, not just the happy path.
- Race conditions, ordering assumptions, state inconsistencies, re-entrancy.
- Async misuse: missing await, fire-and-forget, `.Result`/`.Wait()` blocking, unobserved tasks.
- Resource handling: leaks, missing dispose/close, connections held across awaits.
Focus on large bugs that will be hit in practice. Ignore nitpicks and likely false positives.

## performance  (run together with correctness in deep)
Source: agent-skills five-axis (Performance), references/performance-checklist.
- N+1 queries; unbounded loops or unconstrained data fetching; missing pagination on list endpoints.
- Synchronous work that should be async; large objects created in hot paths.
- Unnecessary re-renders / change-detection churn in UI components.
Report only with a concrete cost ("adds one query per row", not "could be slow").

## adversarial  (deep, arch, quick: leads the pass)
Source: openai/codex-plugin-cc `prompts/adversarial-review.md` (stance and attack surface kept
nearly verbatim), agent-skills doubt-driven-development (assumption checks).

Your job is to break confidence in the change, not to validate it. Find the strongest reasons
this change should not ship yet. Assume it can fail in subtle, high-cost or user-visible ways
until the evidence says otherwise. Give no credit for good intent, partial fixes or likely
follow-up work. If something only works on the happy path, that is a real weakness.

Attack surface (prioritize expensive, dangerous or hard-to-detect failures):
- auth, permissions, tenant isolation, trust boundaries
- data loss, corruption, duplication, irreversible state changes
- rollback safety, retries, partial failure, idempotency gaps
- race conditions, ordering assumptions, stale state, re-entrancy
- empty-state, null, timeout and degraded-dependency behavior
- version skew, schema drift, migration hazards, compatibility regressions
- observability gaps that would hide failure or make recovery harder

Method: actively try to disprove the change. Look for violated invariants, missing guards,
unhandled failure paths, and assumptions that stop being true under stress. Trace how bad
inputs, retries, concurrent actions or partially completed operations move through the code.
Also ask (doubt-driven): what unstated assumptions does this rely on, what hidden coupling or
shared state does it touch, which existing conventions does it break?

In `arch` mode, also challenge the approach itself: is this the right design for the contract,
what assumptions does it depend on, where could the design fail under real conditions?

Each finding answers: what can go wrong, why this path is vulnerable, likely impact,
the concrete change that reduces the risk.

## history  (run together with conventions in deep)
Source: Anthropic code-review agents #3 (git blame/history) and #4 (prior PR comments),
agent-skills code-simplification (Chesterton's Fence).
- For every modified file run at least `git log --oneline -8 -- <file>`, then `git log -L` / `git blame` the modified regions. Does the change remove a guard, check or
  special case that an earlier commit added on purpose? Read that commit message. Does it
  re-introduce a bug an earlier commit fixed? Does it revert a deliberate decision?
- If the repo is on GitHub and `gh` works: find recent merged PRs that touched these files
  (`gh pr list --state merged --search "<path>" --limit 5`) and check whether review comments
  there also apply here.

## conventions  (deep with history, quick, standards)
Sources: Anthropic code-review agents #1 (CLAUDE.md compliance) and #5 (code comments),
pr-review-toolkit comment-analyzer.
- Find CLAUDE.md / AGENTS.md / CONTRIBUTING.md / .editorconfig / lint configs at the repo root
  and in every directory the change touches. Flag a violation only if the file explicitly states
  the rule. Quote the rule and link the file. CLAUDE.md is guidance for writing code, so not every
  line applies to a review.
- Rules explicitly silenced in code (e.g. a lint-ignore with a reason) are not violations.
- Read comments in the modified files near the change. Does the change violate guidance in
  them ("must be called under lock", "keep in sync with X")?
- Comments added or changed by the diff: are they factually accurate against the code
  (parameters, return values, described behavior, edge cases claimed)? Flag comments that are
  now wrong or misleading. Do not flag missing comments.

## errors  (run together with tests in deep, quick)
Source: pr-review-toolkit silent-failure-hunter.
Locate every try/catch, error callback, fallback/default-on-failure, `?.` / `??` / `!` that can
hide a failure, and retry loop in the change. For each:
- Empty catch, catch-log-and-continue, or returning null/empty/default on error without the
  caller knowing.
- Broad catch (`catch (Exception)`, bare `catch {}`) that can hide unrelated errors. Name what it hides.
- Fallback to an alternative path, mock, stub or fake outside tests, not called for by the contract.
- Retry that exhausts silently, retries non-idempotent work, or has no bound/backoff.
- Error swallowed where it should propagate; catch that skips cleanup.
- User-facing message that is generic or misleading about what failed.
Severity guide: silent failure or broad catch on a real path → Important or Critical.

## tests  (deep with errors, test mode)
Sources: pr-review-toolkit pr-test-analyzer, agent-skills code-review step 2 (review tests first,
mutation check), agent-skills test-engineer, superpowers task reviewer.
- Do tests exist for the new or changed behavior? Read tests first: they reveal intent.
- Weakened tests: assertions removed or loosened, `skip`/`only`/`xit`, expected values edited
  to match new output, tests that assert nothing, catch-all mocks that make the test meaningless.
  These are Important findings.
- Critical gaps only: untested error paths that could fail silently, boundary conditions, core
  business-logic branches, negative cases for validation, auth checks. Rate each gap 1–10
  (pr-test-analyzer); report only 8–10 as findings, with the concrete failure it would catch.
- Tests that test implementation instead of behavior, or mock internal functions rather than
  system boundaries. Report only if it makes the test unable to catch a real regression.
- Mutation check (agent-skills): if a test command is approved, invert one condition the change
  adds, run the targeted test, restore from a copy. A mutation that stays green is a finding
  naming the missing test case. Only in test/full mode or when the user approved runs.

## security  (deep, quick-light)
Sources: agent-skills security-auditor and five-axis (Security), Codex attack surface.
Start from trust boundaries (where untrusted data enters) and reason about each one before
listing findings. Only exploitable issues; give an exploitation scenario for Critical/High.
- Injection: SQL/NoSQL/OS command/LDAP via concatenation or interpolation; unencoded output (XSS);
  path traversal; unsafe deserialization.
- AuthN/AuthZ: missing authorization on a new endpoint/handler; IDOR (resource by id without
  ownership/tenant check); privilege checks done client-side only.
- Secrets in code, config or logs; sensitive fields in responses or logs (tokens, card data, PII).
- SSRF (server fetching user-supplied URLs), open redirects, missing webhook signature checks.
- CORS opened to `*` with credentials; security headers removed.
- AI/LLM features: model output into eval/SQL/shell/innerHTML; system prompt used as the only
  permission boundary; secrets or cross-tenant data in the context window.
- New dependencies: from a trusted source, no known CVEs, no typosquats or install scripts.
quick mode runs only the injection, authorization and secrets checks.

## spec  (spec, deep and quick when the contract has requirements, full, pr)
Source: superpowers task-reviewer-prompt (Part 1) and code-reviewer.md.
Compare the diff against every numbered item in `contract.md`:
- **Missing**: a requirement skipped, or claimed without being implemented.
- **Extra**: features not requested, over-engineering, unneeded "nice to haves".
- **Misunderstood**: the right feature built the wrong way, or the wrong problem solved.
- For behavior the contract is silent on, judge by what a reasonable user would expect.
  Silence is not permission. Grade by effect on that user.
- A requirement you cannot verify from the diff (it lives in unchanged code or another
  service): mark it ⚠️ with what to check. Do not broaden the search to prove it.
- If the contract itself mandates something that is a defect (e.g. a test that asserts
  nothing), report it as Important, labeled `plan-mandated`.
- Do not trust the PR description's claims; verify against the code.
- Before finishing, list every behavior you considered and set aside as outside the contract,
  one line each, in `declined`. Only behavior a reasonable user would not expect anyway can be
  declined. "The contract is silent" is never by itself a reason to decline: if a reasonable user
  would expect it (a name with an apostrophe or accent saves and displays unchanged; a date shows
  in the user's own timezone), it is a candidate.
Write, in addition to candidates, `spec_status` per requirement: `met` / `missing` /
`misunderstood` / `cannot_verify` with file:line evidence.

## architecture  (arch, full)
Sources: agent-skills five-axis (Architecture) + structural remedies, api-and-interface-design,
pr-review-toolkit type-design-analyzer, superpowers code-reviewer (architecture).
- Follows existing patterns, or introduces a new one? If new, is it justified by the contract?
- Module boundaries: feature-specific logic leaking into a shared module; dependencies flowing
  the wrong way; circular dependencies; a bespoke near-duplicate of an existing canonical helper.
- Does a refactor reduce complexity or just relocate it? Count the concepts a reader must hold.
- New conditionals bolted onto an unrelated flow; repeated conditionals on the same shape
  (a missing model or dispatcher).
- Type boundaries: gratuitous `any`/`unknown`/`object`/`dynamic`, optional fields or casts that paper
  over an unclear invariant. New types: can invalid instances be created? Are invariants enforced at
  construction and every mutation point? (type-design-analyzer: encapsulation, expression,
  usefulness, enforcement.)
- Public contracts (Hyrum's Law): any observable behavior change, including error text, ordering,
  timing, field types or removals, is a breaking change for someone. Prefer addition over
  modification. One-Version Rule: no parallel versions without a plan.
- API red flags: endpoints returning different shapes by condition; inconsistent error formats;
  validation scattered inside internals instead of at boundaries; list endpoints without pagination;
  verbs in REST URLs; third-party responses used unvalidated; idempotency-key handled with
  SELECT-then-INSERT, per-attempt keys, or a different payload silently replaying the first response.
- Production readiness (superpowers): migration strategy for schema changes, backward compatibility.
Every architecture finding names the structural remedy (agent-skills): replace a conditional chain
with a typed model or dispatcher; collapse duplicate branches; separate orchestration from business
logic; move feature logic to its owning package; reuse the canonical helper; make a type boundary
explicit; delete a pass-through wrapper; extract a helper or split a large file.

## standards  (standards, full)
Sources: agent-skills code-review-and-quality (Readability & Simplicity, change sizing, change
descriptions, dependency discipline, dead code), agent-skills code-simplification.
Compare the change against these standards and the project's written conventions:
- Names that don't describe content (`data`, `result`, `temp`) or mislead (a `get` that mutates).
- Control flow: nesting 3+ deep (use guard clauses), nested ternaries, boolean parameter flags,
  functions 50+ lines doing several things.
- Could this be done in fewer concepts? Abstractions that don't earn their complexity
  (generalized before the third use case), factory-for-a-factory, strategy-with-one-strategy.
- Duplicated logic (5+ lines) that should reuse an existing helper.
- Dead code: unreachable branches, unused variables, commented-out blocks, `// removed` notes,
  back-compat shims nothing calls. List them; ask before deleting.
- Comments that explain *what* instead of *why*.
- File size: a change that pushes a file past ~1000 lines without decomposing it.
- Refactor mixed with feature work in one change (should be separate changes).
- Dependencies: new dependency when the stack already solves it; bulk version bumps without
  changelog review; hand-edited or unreviewed lockfile.
- Change description: vague first line ("fix bug", "phase 1"), no why.
Before proposing removal of anything, apply Chesterton's Fence: check git blame for why it exists.
Each finding gives the concrete simpler version (a 2–6 line sketch is fine). Severity is usually
Minor; Important only when the structure actively gets worse (agent-skills "presumptive blockers").

---

## Candidate schema

`$PKG/candidates/<lens>.json`:

```json
{
  "lens": "errors",
  "files_read": ["src/export/service.ts", "src/export/service.spec.ts"],
  "candidates": [
    {
      "title": "Export failure returns an empty CSV instead of an error",
      "file": "src/export/service.ts",
      "line_start": 42,
      "line_end": 47,
      "severity": "important",
      "body": "What can go wrong, why this path is vulnerable, likely impact.",
      "evidence": "The code path or check you did (e.g. 'caller at routes.ts:88 treats [] as success').",
      "recommendation": "Concrete change.",
      "confidence": 85,
      "contract_ref": "M2",
      "needs_test": false
    }
  ],
  "spec_status": [{"id": "M2", "status": "missing", "evidence": "service.ts:30 has no archived filter"}],
  "declined": ["Considered CSV injection via =formula cells: contract and threat model do not cover spreadsheet consumers."],
  "not_checked": ["Could not reach GitHub for prior PR comments."]
}
```

`severity` is `critical` | `important` | `minor`. `spec_status` and `declined` only for the spec
lens. `contract_ref` is optional. Return an empty `candidates` list when you find nothing.
That is a correct result, not a failure.
