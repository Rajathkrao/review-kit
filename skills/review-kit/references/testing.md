# Running tests and live checks

Sources: superpowers verification-before-completion (no claims without fresh evidence; the
gate function), superpowers task reviewer ("run a test only when reading the code raises a
specific doubt… a focused test, never a package-wide suite"), agent-skills code-review step 2
(mutation check), agent-skills test-engineer (test levels, Prove-It pattern),
agent-skills browser-testing-with-devtools (live UI checks).

The user's standing rule: **ask before running anything**, unless `--run` was passed.
Non-interactive without `--run`: propose only, never run.

## 1. Propose

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/detect_tests.py" "$PKG"
```

It reads the changed files and the repo's tooling (nx, Angular, Jest, Vitest, Karma, dotnet,
pytest, go) and writes `$PKG/test-plan.json`: commands scoped to the change, from cheapest to
most expensive, each with what it covers. Read it, adjust if you know better (e.g. the project's
CLAUDE.md names a test command), and present at most three options with AskUserQuestion:

- **Affected unit tests** (Recommended): the narrowest command that covers the changed files
- **Wider suite**: the project or library test target
- **Skip tests**

Show the exact command in each option's description.

## 2. Run and capture

Run the approved command with a timeout. Write `$PKG/test-results.md`:

```markdown
## Command
npx jest src/export --ci
## Exit code
1
## Summary
14 passed, 1 failed (export.service.spec.ts › excludes archived)
## Relevant output
<the failing assertion and stack, trimmed to what matters>
```

Read the full output and the exit code before writing a summary (verification gate: identify,
run, read, verify, then claim). Warnings and noise in test output count as findings if the change
introduced them.

## 3. Mutation check (test and full modes, only after a run is approved)

Pick 1–3 conditions the change adds. For each: copy the file to `$PKG/mutation/`, invert the
condition (drop a negation, swap `&&`/`||`, change `<` to `<=`), run the same targeted test,
then restore the file from the copy and confirm `git diff` for that file matches the original.
A mutation that stays green is an Important finding that names the missing test case. Always
restore, even when the run fails or times out.

## 4. Live checks

Ask what kind of check fits the change, and let the user steer:

**UI change** (components, templates, styles, routes): hand off to the user's Playwright CLI skill.
Give it the URL or route, the exact steps to exercise the changed behavior, and what to check
(console errors, network failures, the visible result). Read its output into `test-results.md`.
If no Playwright skill is available, say so and list the manual steps.

**Backend change** (endpoints, handlers, jobs, data access): propose, then ask:
- the command to start the service locally (`dotnet run --project …`, `npm run start:api`, …)
- a throwaway probe script written to `$PKG/probes/` (never inside the repo): curl calls or a
  small script that hits the changed endpoint with the happy path plus the edge cases the
  lenses raised (empty, boundary, other tenant's id, retry of the same request)
- the expected result for each probe, so the output can be judged without guessing
Start the server in the background, wait for it to be healthy, run the probes, stop the server.
Save the probe script and output to `test-results.md`.

**Deployed environment URL**: only if the user gives the URL and confirms the environment is safe
to hit. Read-only requests unless they explicitly approve writes.

## 5. Report

The report's **Verification** line summarizes what ran and the result. If nothing ran, it says
why ("not run: user skipped" / "not run: non-interactive without --run"). Never write "tests
pass" from a previous run, a CI badge, or the PR description.
