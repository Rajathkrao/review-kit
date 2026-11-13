# Refine: make the code smaller, clearer and more reusable

`/rk:refine <file | folder | target> [--apply] [--run]` reviews code for structure, not only for
bugs: what to delete, reuse, merge, split or rewrite shorter, with a patch for each and the line
count it saves. The stance is the lazy senior developer who will maintain this: the best code is
the code never written, and every extra line must be read, tested and fixed later.

Order of importance: **correct, safe, holds under load, tested, then lean.** A bug you notice while
simplifying is reported first, as a finding. Lean never beats correct.

## 1. Scope and map

- A file or folder: review its current contents as a whole (the context command reviews a path
  with no pending changes as whole files). A branch, range or PR: review the changed code, plus
  the unchanged code it duplicates or should reuse.
- Before judging, map in one batch of reads: what the code does and who calls it (the call sites
  the context command lists, or `git grep -n -w <name>`), the helpers and patterns the codebase
  already has near it (`git grep` for similar names, the package's `utils`/`common`/`core`
  modules), the installed dependencies (`pyproject.toml`, `requirements*.txt`, `package.json`),
  and the tests that pin its behavior.
- State the expected load (a script run by one person, or a service under concurrency) and judge
  scale against it.

## 2. Look for

**First, what must be fixed** (these go under "Must fix", before any refactor):
- **Bug**: a wrong result, a crash, a missed edge case (empty input, zero, negative, the last item,
  rounding, time zones), a caller broken by the code's contract. An empty input that silently
  produces a malformed result (a CSV with no header, an empty page with no error) counts.
- **Risk**: injection, missing checks on user input, secrets, errors swallowed, writes in the
  wrong order or without a transaction.
- **Scale**: fine for one user, wrong for the expected load: loading every row into memory to
  count or sum it (push it into the query), a query per item, O(n²) on big input, work every
  process repeats, lists that only grow.
- **Missing test**: risky logic (money, parsing, auth, data writes, a branch a refactor below
  touches) with no test that would fail if it broke. One good test, not coverage.

**Then, what to make leaner**, ranked by what it saves:

1. **Delete**: dead code (unreachable branches, unused functions, options, flags, config keys,
   parameters nobody passes, commented-out code, back-compat shims nothing calls). Before calling
   anything unused, grep the whole tree, including tests, fixtures, config, string and dynamic
   references (`getattr`, registries, entry points, `__all__`, templates). One reference found:
   not dead.
2. **Reuse**: the codebase already has this (name the path and line). A near-copy of an existing
   helper, a re-implemented validation, a second HTTP client wrapper, a hand-rolled retry next to
   the project's retry decorator.
3. **Standard library or platform**: the stdlib or an installed dependency already does it.
   Python: `pathlib`, `dataclasses`, `enum`, `functools` (`cache`, `partial`, `reduce`),
   `itertools` (`groupby`, `chain`, `batched`, `pairwise`), `collections` (`Counter`, `defaultdict`,
   `deque`), `contextlib` (`suppress`, `ExitStack`), `any`/`all`/`sum` with generators,
   `str.removeprefix`, `dict | dict`, `zoneinfo`, `statistics`, `shutil`, `tempfile`, `secrets`.
   A new dependency for a few lines is a finding; so is a dependency the stdlib now covers.
4. **YAGNI**: an abstraction with one implementation, a factory with one product, a base class
   with one subclass, a strategy with one strategy, a wrapper that only passes calls through,
   config nobody sets, a plugin system with one plugin, generality "for later".
5. **Merge**: near-copies that must change together (same shape, different constants): one
   function with a parameter, a table of data, or a loop.
6. **Simplify flow**: nesting 3+ deep (guard clauses and early returns), `if/elif` chains on one
   value (a dict or `match`), flag parameters that switch behavior (two functions), manual index
   loops (`enumerate`, `zip`, comprehension), accumulate-then-return loops (`sum`, `any`, a
   comprehension), try/except used for control flow, temporary variables used once, double
   negatives, repeated lookups.
7. **Structure for reuse**: one function doing several unrelated jobs (split by job, never by line
   count, never into helpers that exist only to shorten a function); business logic mixed with
   I/O (separate the pure part so it can be tested and reused); feature logic inside a shared
   module (move it to its owner); a dict passed through layers where a small `dataclass` or
   `TypedDict` would name the fields. Extract a reusable component only when two real callers
   exist now, in this code or in the change.
8. **Types and names that lie**: a `get_` that mutates, a return type that is sometimes `None`,
   a name that no longer matches what the code does after the change.

## 3. Check before you propose

- **Behavior is preserved.** For each refactor, name what must stay the same: return values,
  raised exceptions, side effects and their order, logging, edge cases (empty, None, duplicates),
  performance class. If anything changes, it is not a refactor; say so or drop it.
- **Every caller still works.** Read the call sites of anything whose signature or behavior you
  touch.
- **Shorter means easier to read.** A one-liner that needs decoding is not shorter. Clever
  comprehensions nested two deep, chained ternaries and dense lambdas are rejected.
- **Keep the codebase's shape**: its layers, conventions and error handling. Code you move or
  merge keeps its validation and error handling.
- **Never cut**: validation at trust boundaries, error handling that prevents data loss,
  security checks, accessibility, anything a test or the contract requires.
- A `shortcut:` comment naming its limit is a decision, not a finding, unless the load crosses it.
- No taste, no "consider", no rename-only suggestions, nothing a formatter does.

## 4. Output

```markdown
## Refine · <target>

**What this code does:** <two or three plain sentences> · assumed load: <one line>
**Verdict:** <"Lean already" | "fix 1 first, then refactor 2–5">
**Lean:** −<N> lines, −<M> dependencies possible · <k> refactors

### Must fix (bugs seen while refactoring)
**1. Important: <title>** `path:12-18`
<problem, trigger, fix: same shape as a review finding>

### Refactors
**2. Reuse `billing/money.py:split_cents` instead of a second splitter** `payouts/service.py:19-22` · −4 lines
- **Now:** <what the code does today, one sentence>
- **Better:** <the change and why it is simpler or safer, one or two sentences>
- **Same behavior because:** <what stays identical; callers checked>
```diff
-    each = amount_cents / n
-    return [round(each) for _ in range(n)]
+    return split_cents(amount_cents, n)
```

### Considered and kept
- <a structure that looks heavy but earns its place, one line why>
```

Number everything across sections so the user can say "apply 2 and 4". Order refactors by lines
saved and risk: big safe deletions first. At most 15 refactors; say how many smaller ones you left.

## 5. `--apply`

Only with `--apply`, or when the user asks ("apply 2 and 4"). Apply in order, one refactor at a
time. After each, run the narrowest test that covers it (ask first unless `--run`), and revert that
refactor if the test fails. Never apply a refactor whose behavior you couldn't show is preserved.
Finish with the diff stat, tests run and their results, and what was reverted and why.
