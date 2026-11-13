---
description: "Code review with automatic depth (quick for small changes, deep for large or risky ones). Pass a mode first to choose"
argument-hint: '[mode] [target] [--html] [--focus "text"] [--run] [--all]'
---

Load the `rk:review-kit` skill with the Skill tool and run it.

Arguments from the user: `$ARGUMENTS`

If the first argument is a mode name, use it. If the only argument is a PR number or PR URL, use
`pr` mode. Otherwise use `review` mode (automatic depth). Do not ask which mode to run.
