---
description: "Code review with review-kit. Pick a mode, or pass one first (quick, deep, spec, pr, test, arch, standards, full)"
argument-hint: "[mode] [target] [--html] [--second-model] [--post] [--run] [--all] [--focus \"text\"]"
---

Load the `rk:review-kit` skill with the Skill tool and run it.

Arguments from the user: `$ARGUMENTS`

If the first argument is a mode name, use it. If the only argument is a PR number or PR URL, use
`pr` mode. Otherwise ask which mode to run, as the skill describes.
