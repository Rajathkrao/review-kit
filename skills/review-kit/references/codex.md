# Codex runtime mapping

Resolve the directory containing this skill's `SKILL.md` to an absolute path.
Use it wherever the pipeline says `${CLAUDE_SKILL_DIR}`; Codex does not set that
Claude variable. Resolve all scripts, references and assets relative to it.

Read files with the available file tools or shell; use `rg` for searches. Execute
the bundled Python/shell helpers using the available terminal tool. Preserve
their output and exit status. Do not claim a helper succeeded after failure.

Use `$review-kit deep <target> --html --run` as the equivalent of `/rk:deep`.
The invocation supplies arguments directly; do not expect `$ARGUMENTS` expansion.
Use the user's stated mode and test authorization. When clarification tools are
unavailable, follow the skill's non-interactive defaults and disclose them.

Registered Claude agent types `rk:lens-reviewer` and `rk:finding-verifier` are not
required in Codex. Use the host's general subagent tool with the same role:
- Lens: give only lens name, package path, contract path, relevant sections of
  `references/lenses.md`, focus and output path. Apply its shared rules/schema.
  Read source only; do not execute tests or spawn further reviewers in a lens.
- Verifier: give the package, merged candidates, test evidence and
  `references/verification.md`. Require rereading, attempted disproof, calibrated
  scores and `findings.json`. Do not pass the coordinator's conclusions.

Run independent lenses concurrently within the host's resource limits; use
batches when necessary. If subagents are unavailable, run lenses sequentially
with separate notes and explicitly disclose that verification was not isolated.
Never imply that installing this skill supplies a different model, CLI login or
GitHub credentials. `--second-model` still requires a genuinely different model.

For `--html`, produce the same explainer JSON and run `scripts/render_html.py`;
verify the generated page reflects the final findings and reports. Report the
actual runtime and model when known instead of labeling every reviewer Claude.
