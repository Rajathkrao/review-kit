# Second-model review (`--second-model`)

Different models have different blind spots (agent-skills multi-model review pattern; Codex
plugin: "uncorrelated failure modes"). The second model reviews the same package
independently, with no access to your conclusions or the other lenses' candidates.

Sources: agent-skills doubt-driven-development (cross-model escalation rules: verify the CLI
works, pass only artifact + contract, use stdin, read-only sandbox, never silently skip),
openai/codex-plugin-cc (adversarial prompt and output schema).

## Order of preference

1. **Codex CLI**, if `codex` is on PATH and logged in.
2. **A different Claude model** as a subagent: if the session runs on Opus, use Sonnet;
   otherwise use Opus. Spawn `rk:lens-reviewer` with the `model` parameter set and the
   `adversarial` lens.

## Codex

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/codex_review.sh" "$PKG"
```

The script:
- checks `codex --version` and `codex login status`; exits 3 with a message if unavailable
- builds `$PKG/codex-prompt.md` from the Codex adversarial prompt (`assets/codex-adversarial-prompt.md`)
  with the contract, focus and diff inserted
- runs `codex exec --sandbox read-only -C <repo> --output-schema <schema> -o $PKG/codex-output.json -`
  with the prompt on stdin (never as a shell argument: diffs contain backticks and `$()`)
- retries once without `--output-schema` if that flag is rejected
- converts Codex's output (severity critical/high/medium/low, confidence 0–1) into a candidates file
  at `$PKG/candidates/second-model.json` (high→important, medium/low→minor, confidence ×100)

Run it in the background (Bash `run_in_background: true`) while the lenses run. It typically
takes 2–6 minutes. If it exits 3 (unavailable), fall back to a Claude model and say so.

Interactive runs: before the first Codex call in a session, confirm once: "Run Codex
read-only on this diff? It uses your OpenAI account." Non-interactive runs use Codex only when
`--second-model` was passed explicitly.

## In the report

The `Scope` line always says what happened: `second model: codex`, `second model: claude-sonnet
(codex not installed)`, or `second model: skipped (user declined)`. Second-model findings go
through the same verifier as every other candidate. Findings only the second model found are
tagged `found_by: codex`, which tells you where the cross-model value came from.
