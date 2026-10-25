# HTML explainer (`--html`)

A self-contained page that teaches the reader what the change does, step by step, in the order
it executes at runtime, and shows where each finding sits in that flow. It's for understanding a
change you didn't write, or explaining your own to someone else.

The reader may not know this codebase. Write for a capable engineer seeing this area for the
first time: plain words, name things before using them, no unexplained jargon.

## 1. Write `$PKG/explainer.json`

Trace the change yourself (read the diff and the code it calls) and write:

```json
{
  "title": "Invoice CSV export",
  "one_liner": "Adds GET /invoices/export, which streams the caller's invoices as CSV.",
  "why": "From ADR-0007: finance users need monthly exports without a support ticket.",
  "before": "There was no export; users copied rows from the invoice list page.",
  "after": "A new endpoint builds the CSV on the server, capped at 10,000 rows.",
  "entry_point": "GET /invoices/export?month=2026-09",
  "steps": [
    {
      "title": "Request arrives at the controller",
      "where": "src/export/export.controller.ts:14-29",
      "what_happens": "Reads `month` from the query string and the tenant id from the auth token, then calls the service.",
      "snippet": "const tenantId = req.user.tenantId;\nreturn this.service.export(tenantId, month);",
      "kind": "request",
      "finding_ids": []
    },
    {
      "title": "Invoices are loaded",
      "where": "src/export/export.service.ts:30-41",
      "what_happens": "Queries invoices for the tenant and month. Archived invoices are not filtered out.",
      "snippet": "...",
      "kind": "data",
      "finding_ids": ["F2"]
    }
  ],
  "key_concepts": [
    {"term": "Tenant", "meaning": "A customer organization. Every query must be scoped to one."}
  ],
  "try_it_yourself": [
    "Call the endpoint for a month that contains an archived invoice; it should not appear.",
    "Request more than 10,000 rows; expect HTTP 413."
  ],
  "changed_files": [
    {"path": "src/export/export.service.ts", "role": "Builds the CSV", "change": "new"}
  ]
}
```

Rules:
- `steps` follow execution order from `entry_point`, not file order. 3–10 steps. If the change has
  several independent entry points (e.g. an endpoint and a background job), give each its own run
  of steps and start the first step of each run with the entry point in its title.
- `snippet` is 1–8 lines copied from the new code, trimmed with `...`. Never invent code.
- `kind` is one of `request` `data` `logic` `ui` `job` `config` `test` `external`.
- Every finding in `findings.json` should attach to the step where its problem happens. A
  finding that doesn't belong to any step goes in a step titled "Elsewhere in the change".
- `try_it_yourself` comes from the contract and the findings: concrete checks with expected results.

## 2. Render

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/render_html.py" "$PKG"
```

The page is written to `$PKG/review.html`, in the run folder `<repo>/.review-kit/runs/<date>-<mode>-<target>/`.
It contains: summary and verdict, a vertical flow diagram of the steps with finding badges,
each step expanded with snippet and plain explanation, findings with fix and evidence, spec
compliance, test evidence, key concepts, try-it-yourself checks, changed files, and (collapsed)
the dropped candidates with the reason each was dropped. Works offline, light and dark mode.

Give the user the path. If the session can open files (desktop app), offer to open it.
