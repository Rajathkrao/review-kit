# HTML walkthrough

A self-contained page that teaches the reader what the change does, in the order it runs, and
explains every problem deeply enough to fix it without re-reading the diff. It's written for the
person who just wrote the code, or a reviewer seeing this area for the first time.

Written by default in `deep`, `full`, `pr` and `arch` modes, and in any mode with `--html`.
`--no-html` or `"html": "never"` in config skips it. `"html": "always"` writes it in every mode.

**You never copy code into this file.** The renderer reads the real source of the reviewed commit
and marks changed lines from the diff. You point at files and line numbers; it shows the code.

## 1. Write `$PKG/explainer.json`

Trace the change yourself: read the diff and the code it calls. Then write:

```json
{
  "title": "Monthly renewal job",
  "one_liner": "Adds a cron job that charges every due subscription and moves its billing date forward a month.",
  "why": "From docs/renewals.md: each subscription is charged once per period, never twice.",
  "before": "Nothing charged subscriptions automatically.",
  "after": "Every minute, on each worker, runRenewals charges subscriptions whose nextBillingAt has passed.",
  "entry_point": "renewalCron.run() every minute on each worker",
  "steps": [
    {
      "title": "Page through active subscriptions",
      "kind": "data",
      "file": "src/renewals.ts",
      "lines": [38, 50],
      "explanation": "Two or three short paragraphs: what this code does, what state it reads and changes, and what it assumes.",
      "notes": [{"line": 49, "text": "Cursor is the last row's createdAt, which is not unique."}],
      "finding_ids": ["F1", "F4"]
    }
  ],
  "problems": {
    "F1": {
      "pin_line": 45,
      "line_note": "Reads and charges with no claim: every worker charges this row.",
      "summary": "Two or three sentences a newcomer understands: what goes wrong, for whom, and when.",
      "scenario": [
        "At 09:00:00 workers A, B and C each start runRenewals.",
        "All three read sub_42 with nextBillingAt = today; none has changed it yet.",
        "Each calls gateway.charge('c_42', 1500).",
        "The customer is charged $45 instead of $15."
      ],
      "failure_step": 4,
      "trace": [
        {"file": "src/cron.ts", "line": 3, "step": "1", "note": "Fires on all 3 workers every minute."},
        {"line": 29, "step": "5", "note": "The date moves only after charging, too late to stop the others."}
      ],
      "root_cause": "The assumption that is wrong, and why the code made it. Not a restatement of the symptom.",
      "impact": "Who is affected, how often, how bad, and whether anyone would notice. Quantify when you can.",
      "fix": {
        "explanation": "The change and why it removes the root cause. Mention an alternative if there is a real trade-off.",
        "file": "src/renewals.ts",
        "patch": "-  const { chargeId } = await chargeWithRetry(sub);\n+  if (!(await subscriptionRepo.claimPeriod(sub.id, sub.nextBillingAt))) return 'skipped';\n+  const { chargeId } = await chargeWithRetry(sub);"
      },
      "test": {
        "name": "test/renewals.concurrency.test.ts",
        "explanation": "What the test does, and what it shows today (it fails) and after the fix (it passes).",
        "code": "test('three workers charge once', async () => { ... });"
      }
    }
  },
  "key_concepts": [{"term": "Idempotency key", "meaning": "A value that lets a server perform a request at most once, however often it is retried."}],
  "try_it_yourself": ["Run three runRenewals calls in parallel against one due subscription: expect one charge."],
  "changed_files": [{"path": "src/renewals.ts", "role": "The renewal job", "change": "new"}]
}
```

### The walkthrough (`steps`)

- Follow **execution order** from `entry_point`, not file order. 3 to 10 steps. Several entry
  points (an endpoint and a job) each get their own run of steps.
- `file` + `lines` select the code shown, so keep each range to one function or block (under ~40
  lines). Line numbers come from `diff-numbered.txt` (left column) or the file itself.
- `explanation` teaches: what the code does, the data it touches, and the assumption it makes.
  Name things before using them. Write for a capable engineer new to this area.
- `notes` put a short margin note on a specific line, for a subtle point that isn't a problem.
- `finding_ids` lists the problems whose lines sit in this step. A problem may belong to no step.
- `kind` is one of `request` `data` `logic` `ui` `job` `config` `test` `external`.

### Each problem, in depth (`problems`, keyed by the finding id in `findings.json`)

Every finding in `findings.json` gets an entry. Depth here is the point of the page:

- `pin_line`: the line where the problem actually happens (the call without a key, the condition
  that's inverted), not the first line of the function.
- `scenario`: the concrete sequence that triggers it, as 3 to 7 ordered events with real values
  (ids, amounts, timestamps, inputs). Someone should be able to reproduce it from this list.
  `failure_step` is the 1-based step where the damage happens (default: the last).
- `trace`: the path through the code, as margin notes on the lines that matter, numbered with the
  scenario `step` they belong to. Use `file` for lines in another file.
- `root_cause`: the wrong assumption, not the symptom. "Charging and claiming the period are
  separated by a network call" explains; "it double-charges" does not.
- `impact`: who is affected, how often, how bad, and whether it is visible or silent.
- `fix.patch`: a unified-diff-style excerpt (`-` old, `+` new, ` ` context) small enough to read.
  It must be correct for this codebase; if the full fix is larger, show the core and say so.
- `test`: a focused test that fails today and passes after the fix, in the project's test style.

Unverified ideas never go here: only findings that survived verification.

## 2. Render

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/render_html.py" "$PKG"
```

The page is written to `$PKG/review.html` in the run folder. The renderer validates
`findings.json` first and refuses to render invalid data. Give the user the path. If the session
can open files (desktop app), offer to open it.
