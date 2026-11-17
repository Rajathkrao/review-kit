# Refine: make the code smaller, clearer and easier to change

`/rk:refine <file | folder | target> [--apply] [--run] [--for "<next change>"] [--comments] [--tests]`
reviews code for structure, not only for bugs. It works at two levels in one pass:

- **Moves**: at most three structural changes, each one removing several problems at once
  (a missing concept, a module in the wrong place, a tie that should not exist).
- **Refactors**: line-level changes (delete, reuse, merge, flatten), each with a patch and the
  lines it saves.

The stance is the lazy senior developer who will maintain this: the best code is the code never
written, every extra line must be read, tested and fixed later, and a change should land in one
place. Nothing is asked up front; options are flags.

Order of importance: **correct, safe, holds under load, tested, then lean.** A bug you notice while
simplifying is reported first, as a finding. Lean never beats correct.

## 1. Scope and map

- A file or folder: review its current contents as a whole (the context command reviews a path
  with no pending changes as whole files). A branch, range or PR: review the changed code, plus
  the unchanged code it duplicates or should reuse.
- The context command prints a **structure map** measured from the code and git history: a
  scoreboard (code lines, longest function, nesting, special cases), the special cases
  themselves, pass-through wrappers, copied function bodies, repeated literals, names nothing
  else mentions, who imports whom, which files keep changing, and which files change together
  without importing each other. Start from it instead of crawling. Every line in it is a lead:
  open the code before you believe it. Over ~1500 code lines it also prints a skeleton
  (signatures only); read bodies only where a lead or a caller points.
- Then, in one batch of reads: who calls the code (the call sites the context command lists, or
  `git grep -n -w <name>`), the helpers the codebase already has near it (`git grep` for similar
  names, the package's `utils`/`common`/`core` modules), the installed dependencies
  (`pyproject.toml`, `requirements*.txt`, `package.json`), and the tests that pin its behavior.
- State the expected load (a script run by one person, or a service under concurrency) and judge
  scale against it.
- Use the project's own words. Name things the way its docs, glossary, ADRs and existing code
  name them; never invent a `Manager`, `Handler` or `Processor` the domain doesn't have.
- **`--for "<next change>"`** (or the user says what they are about to build): the question
  becomes "what would make that change land in one place?". Rank everything by how much it helps
  that change, and leave out cleanups that don't touch its path. Without it, rank by where change
  keeps landing (the map's git history): a mess nobody edits costs nothing.

## 2. First, what must be fixed

These go under "Must fix", before any move or refactor:
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

## 3. Structure: three tests, then group by cause

Run these on the map's leads and on what you read. Each lead that survives is a **problem**; do
not write a refactor for it yet.

**A. Change-together test.** For each piece, ask: when this changes, what else has to change?
- *Apart, but they change together*: the same rule or value in two places, a module that reads a
  global, file or env var another one writes, an order of calls nothing enforces, one feature
  smeared over several layers so a small change opens five files, two files the git history shows
  changing together with no import between them. Fix: put them in one place, or make the link
  visible (one shared definition, a type, a function that owns the order).
- *Together, but they change for different reasons*: a caller reaching into another module's
  internals, a general function that takes a parameter only one caller understands, a shared
  helper with a branch per feature, code many files depend on importing code that changes often
  (the map marks these `STABLE ON VOLATILE`), an import cycle. Fix: cut the tie, turn the
  dependency around, or move the feature's part back to the feature.

**B. Delete-it test.** For each wrapper, class, layer and module, imagine it gone.
- Nothing is lost, the callers just call what it called: it is surplus. Delete it.
- Its job reappears, copied, in every caller: it earns its place. Keep it, and say so under
  "Considered and kept".
- Callers must still know almost everything it knows (they pass its internals in, call it in a
  set order, unpack what it returns): it is shallow. Either fold it into its one caller, or make
  it deep: move the steps every caller repeats behind one small call. A pure function pulled out
  only so it could be tested, while the bugs live in how callers combine it, is this case.

**C. Special-case test.** The map lists them: a branch for one value, a parameter for one caller,
a swallowed exception, a sleep or retry, a skipped test, a silenced check, a workaround note. Each
is one of three things, and you decide which by reading it:
- a real requirement nobody wrote down: keep it, and give it a name (a constant, a table row, a
  function) so it stops looking like an accident;
- a symptom of a missing concept: three branches on `kind == ...` in three functions are one
  missing type or one table. This is where moves come from;
- a leftover: the caller, flag or bug it served is gone. Delete it, after the grep in "Delete"
  below.
The number of special cases is the best single measure of how tangled the code is. Report it
before and after.

**Group by cause.** Now look at the problem list as a whole and ask: if this code had been written
knowing today's requirements, what would be different? Look for the one change that makes several
problems disappear, even when it resembles none of them: a table instead of scattered branches, a
small type instead of a dict threaded through four functions, one owner for a rule that lives in
three places, an interface where callers ask which provider they have. That change is a **move**.
- A move must remove at least two listed problems or it is an ordinary refactor.
- At most three moves, the strongest first. One move well argued beats five sketched.
- Give each a strength. **Strong**: the tests above pass clearly and the cost is paid today
  (churn, a bug, duplicated edits). **Worth exploring**: sound, but the payoff depends on where
  the code is heading; say what would settle it. Anything weaker is not reported; count it in
  one line.
- Problems no move covers fall through to the refactor list below.
- Small, tidy code has no moves. Say "no structural move needed" and go on; never invent one.

## 4. Then, what to make leaner

Line-level refactors, ranked by what they save. Skip any that a move already covers.

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

## 5. Check before you propose

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
- **A move is a sequence of safe steps**, each leaving the tests green: add the new shape beside
  the old, switch callers over, delete the old. If you cannot break it into such steps, it is a
  rewrite; say so and do not offer it under `--apply`.
- **Obey earlier decisions.** A structure listed in the learnings file as kept on purpose is not
  proposed again unless the reason given there no longer holds.

## 6. Output

```markdown
## Refine · <target>

**What this code does:** <two or three plain sentences> · assumed load: <one line>
**Verdict:** <"Lean already" | "fix 1 first, then move 2, then refactors 3–6">
**Scoreboard:** <N> code lines · <S> special cases · longest function <L> lines
**After everything below:** about −<N> lines · special cases <S> → <S2> · −<M> dependencies · <k> refactors

### Must fix (bugs seen while refactoring)
**1. Important: <title>** `path:12-18`
<problem, trigger, fix: same shape as a review finding>

### Moves (structure)
**2. One fee table instead of per-plan branches** · Strong · −31 lines · special cases −5
- **Removes:** the `plan == "gold"` branches at `fees.py:14`, `invoice.py:40`, `report.py:22`;
  the duplicated rate `0.015` (`fees.py:9`, `report.py:7`); the `skip_fee` flag on `charge()`
- **Now:** <how it works today and what a typical change costs, one or two sentences>
- **After:** <the new shape in the project's words, and where a typical change lands>
- **Shape:**
  ```text
  before: charge() ─┬─ if plan == "gold" …     invoice() ── if plan == "gold" …
                    └─ if skip_fee …            report()  ── RATE = 0.015 (copy)
  after:  FEES[plan] ◄── charge(), invoice(), report()
  ```
- **Steps:** 1) add `FEES` in `fees.py` 2) `charge()` reads it 3) `invoice()`, `report()` read it
  4) delete `skip_fee` and the copies
- **Pinned by:** `tests/test_fees.py::test_gold_rate`; nothing covers `report()`: add one test first
- **Same behavior because:** <what stays identical; callers checked>

### Refactors
**3. Reuse `billing/money.py:split_cents` instead of a second splitter** `payouts/service.py:19-22` · −4 lines
- **Now:** <what the code does today, one sentence>
- **Better:** <the change and why it is simpler or safer, one or two sentences>
- **Same behavior because:** <what stays identical; callers checked>
```diff
-    each = amount_cents / n
-    return [round(each) for _ in range(n)]
+    return split_cents(amount_cents, n)
```

### Considered and kept
- <a structure that looks heavy but earns its place, or a special case that is a real requirement, one line why>
```

Number everything across sections so the user can say "apply 2 and 4". Order refactors by lines
saved and risk: big safe deletions first. A refactor that a move makes pointless is not listed
separately. At most 15 refactors; say how many smaller ones you left. The "Shape" sketch is
plain text, 2 to 6 lines; skip it when a sentence says it. A move's patch may be a sketch of the
new definition plus one switched caller rather than the full diff.

## 7. `--apply`

Only with `--apply`, or when the user asks ("apply 2 and 4"). `--run` pre-approves running tests;
without it, ask once before the first run.

1. **Baseline.** Run the tests that cover the target before touching anything. Tests that already
   fail are reported and are not yours to fix. No tests at all: say so, and apply only refactors
   whose behavior you can show from the code alone (deletions of unreferenced code, stdlib
   swaps); leave moves as proposals.
2. **Pin before you move.** Where a move or a risky refactor touches behavior no test covers,
   first write one small test that records what the code does today (inputs through the public
   entry point, exact outputs and errors) and see it pass. It stays in the diff.
3. **One step at a time**, in report order, a move as its listed steps. After each, run the
   narrowest test that covers it; if it fails and one more try doesn't fix it, revert that step
   and everything of its move already applied, and go on.
4. **Measure.** Run `python3 "${CLAUDE_SKILL_DIR}/scripts/refine_map.py" --compare "$PKG/refine-before.json"`
   (it re-measures the same files) and put its table in the summary.
5. **Look once more.** Read the new map's leads for the files you changed. Apply what the moves
   newly exposed (a wrapper that now only forwards, a parameter nobody passes) under the same
   rules. One extra round, not a loop; list what remains.

Never apply a change whose behavior you couldn't show is preserved. "Must fix" items change
behavior, so `--apply` alone leaves them as reported; fix one only when the user names it
("apply 1") or through `/rk:fix`, and say which were left. Finish with the scoreboard table, the
diff stat, tests run and their results, what was reverted and why, the public names that no
longer exist (code outside this repository may import them), and what you left. Never commit,
push or touch the index: delete files with `rm`, not `git rm`.

## 8. Optional cleanups (flags; never on by default, never asked about)

- **`--comments`**: also remove comments that only repeat what the code says, including ones
  dressed up as a reason ("increment the counter because we need to count"). Keep every comment
  that states a fact the code cannot: why, a limit, the behavior of an outside system, a link to
  a bug. A workaround comment goes only when the workaround does.
- **`--tests`**: also review the tests that cover the target. Flag a test that cannot fail
  (asserts nothing, asserts a mock was called the way the test told it to), a test that repeats
  the implementation line for line, and a test tied to internals a refactor would break without
  any behavior changing (rewrite it against behavior). With `--apply`, test changes go last,
  after the code is green, and no test is deleted in the same step as the code it covers.

## 9. When someone rejects a suggestion

If the user says a structure stays, with a reason, append one line to
`<repo>/.review-kit/learnings.md` ("refine: keep the `Exporter` base class, a second exporter is
planned for Q1"). Later runs read it and list that structure under "Considered and kept".
