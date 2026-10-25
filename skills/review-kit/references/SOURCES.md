# Where every rule comes from

review-kit adds orchestration, scripts and formatting. The review criteria themselves are taken
from these four projects. If a rule is not traceable to one of them, it does not belong in a lens.

| Source | License | Files used |
|---|---|---|
| **AS** addyosmani/agent-skills | MIT | skills/code-review-and-quality, code-simplification, api-and-interface-design, doubt-driven-development, documentation-and-adrs, browser-testing-with-devtools; agents/security-auditor, test-engineer, code-reviewer |
| **SP** obra/superpowers | MIT | skills/requesting-code-review (code-reviewer.md), receiving-code-review, subagent-driven-development (task-reviewer-prompt.md, final-review.md), verification-before-completion |
| **CX** openai/codex-plugin-cc | Apache-2.0 | prompts/adversarial-review.md (copied with "Codex" removed, in assets/), schemas/review-output.schema.json (copied), commands/adversarial-review.md, prompts/stop-review-gate.md |
| **AN** anthropics/claude-plugins-official | Apache-2.0 | plugins/code-review/commands/code-review.md; plugins/pr-review-toolkit agents: code-reviewer, silent-failure-hunter, pr-test-analyzer, type-design-analyzer, comment-analyzer; commands/review-pr.md |

## Rule map

| review-kit element | Source |
|---|---|
| Review against the plan/spec; Missing / Extra / Misunderstood; spec is a vision document; ⚠️ cannot verify; plan-mandated defects; declined-to-judge list; don't trust the report | SP task-reviewer-prompt, code-reviewer.md |
| Understand intent before reading code; review tests first | AS code-review-and-quality steps 1–2 |
| Match ADR conventions (locations, `.adr-dir`) when searching for purpose docs | AS documentation-and-adrs |
| Five axes: correctness, readability, architecture, security, performance | AS code-review-and-quality |
| Structural remedies; presumptive blockers; refactor relocates vs reduces complexity | AS code-review-and-quality |
| Change sizing (~100/~300/~1000), file size ~1000, split strategies | AS code-review-and-quality |
| Dependency discipline, lockfile review, one dependency per change | AS code-review-and-quality |
| Dead code: list and ask before deleting | AS code-review-and-quality |
| Severity labels Critical / Required(Important) / Nit / Optional / FYI; lead with what matters | AS code-review-and-quality |
| Mutation check (invert a condition, run, restore) | AS code-review-and-quality step 2 |
| Simplification patterns, Chesterton's Fence, Rule of 500 | AS code-simplification |
| Hyrum's Law, One-Version Rule, addition over modification, API red flags, idempotency-key rules | AS api-and-interface-design |
| Security scope, trust boundaries + STRIDE, exploitable-only, PoC for Critical/High, LLM checks | AS security-auditor |
| Test scenarios, test levels, Prove-It pattern | AS test-engineer |
| Fresh-context adversarial reviewer gets artifact + contract, not conclusions; RECONCILE classes; cross-model escalation (verify CLI, stdin, read-only sandbox, never skip silently) | AS doubt-driven-development |
| Multi-model review pattern | AS code-review-and-quality |
| Adversarial stance, attack surface, review method, finding bar, grounding, calibration, final check | CX adversarial-review.md |
| "Challenge the approach, not just the defects" framing for arch mode | CX commands/adversarial-review.md |
| Output schema (verdict, findings with file/lines/confidence/recommendation); terse ship/no-ship summary | CX review-output.schema.json, adversarial-review.md |
| Second-order failures, empty state, retries, stale state, rollback (dig-deeper nudge) | CX stop-review-gate.md |
| Parallel lenses: CLAUDE.md, shallow bug scan, git blame/history, prior PR comments, code comments | AN code-review steps 2–4 |
| 0–100 confidence rubric (verbatim), ≥80 filter, false-positive list | AN code-review steps 5–6; AN pr-review-toolkit code-reviewer |
| Eligibility check and re-check before posting; GitHub link format with full SHA and context lines; gh only | AN code-review |
| Silent failures, broad catches, unjustified fallbacks, hidden errors per catch | AN silent-failure-hunter |
| Test-gap criticality 1–10, behavior over implementation, DAMP | AN pr-test-analyzer |
| Type invariants: encapsulation, expression, usefulness, enforcement | AN type-design-analyzer |
| Comment accuracy and comment rot | AN comment-analyzer |
| Aggregate by Critical / Important / Suggestions | AN review-pr |
| Evaluate existing PR comments: verify against the codebase, YAGNI check, push back with reasons, thread replies via the replies endpoint, no performative agreement | SP receiving-code-review |
| No claims without fresh evidence; the verification gate; "tests pass" needs output from this session | SP verification-before-completion |
| Focused tests only, never full suites, inside review | SP task-reviewer-prompt |
| Read-only reviewer; reviewers don't spawn reviewers | SP code-reviewer.md, task-reviewer-prompt |
| Severity calibration ("Important = can't be trusted until fixed") | SP task-reviewer-prompt |
| Live UI checks in the browser | AS browser-testing-with-devtools (handed to the user's Playwright CLI skill) |

## What review-kit adds (not review criteria)

Mode routing; the package collector; purpose-doc discovery; the separate verifier stage; dropping
below-threshold findings with recorded reasons; caps on finding counts; the HTML walkthrough; the
PR payload builder; Codex fallback to a different Claude model. These are plumbing around the
sources' rules, not new rules about what makes code good.
