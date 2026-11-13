# Harder eval set (Python)

The original five fixtures in `../fixtures.tgz` are saturated: quick and deep find every planted
bug. This set is meant to separate versions again. It is Python-only, because that is what the
skill is mainly used for, and it is built to make three things show up:

- **Bugs a verifier is tempted to drop.** Several of them look rare or theoretical: a task the
  event loop only holds weakly, a late-binding lambda, a UTC date used where the store's local
  date is meant, a race between a count and an insert, a cache that is only stale on the second
  call. Every one is real. Each was reproduced by running the fixture code (see "Checked" below).
- **A diff over the collector's 1,000-line limit.** `py-ledger:feature/multi-currency` changes about
  1,240 lines in 20 files. Its five bugs sit among a currency table, an OFX importer and a lot of
  tests.
- **False alarms.** Four of the nine branches are correct changes. Some include code that looks
  wrong but is not, such as negative amounts left unescaped in a CSV export (they are numbers)
  and a counter changed without a lock in a coroutine with no `await` in between.

| Case | Kind | Size | Planted | Contract |
|---|---|---|---|---|
| `py-ledger:feature/multi-currency` | money, refactor | 20 files, +1098/−138 | 5 (L1–L5) | `docs/adr/0003-multi-currency.md` |
| `py-ledger:feature/statement-export` | clean | 3 files, +107 | 0 | none |
| `py-uploads:feature/bundle-upload` | Flask, file security | 6 files, +157/−6 | 4 (U1–U4) + 2 nice | `docs/bundles.md` |
| `py-uploads:feature/safe-content-type` | clean | 2 files, +56/−1 | 0 | none |
| `py-jobs:feature/concurrent-dispatch` | asyncio | 11 files, +270/−37 | 5 (J1–J5) + 1 nice | `docs/dispatch.md` |
| `py-jobs:fix/structured-logging` | clean | 2 files, +64/−2 | 0 | none |
| `py-shop:feature/coupon-redemption` | Django | 8 files, +196/−2 | 5 (D1–D5) | `docs/coupons.md` |
| `py-shop:feature/coupon-admin` | clean | 2 files, +112 | 0 | none |
| `py-ingest:feature/ingest-v2` | NDJSON ingest, SQL, Flask | 13 files, +292/−8 | 9 (H1–H16) + 1 nice | `docs/ingest-v2.md` |

The answer keys are in `../answer-keys.json` (cases with `"set": "hard"`). Each item has an
`anchor`, which is a piece of text that must appear on the item's lines. `../check_keys.py`
enforces this in CI, so the line numbers cannot drift when a fixture is edited.

## Where the bugs come from

These are bug classes that come up again and again in public Python code and CVEs, rebuilt in
small apps so the answer is unambiguous. They are not copies of specific upstream PRs.

| Id | Bug | Public reference |
|---|---|---|
| U1 | tar members may be symlinks/hard links; no extraction filter on Python 3.11 | CVE-2007-4559, PEP 706 |
| U2 | path check with `startswith` before normalising | CWE-22 |
| U3 | `re.match` used where `fullmatch` was meant: the slug check only anchors at the start | common validation bypass |
| U4 | upload size checked, extracted size not (decompression bomb) | CWE-409 |
| J1 | `asyncio.create_task` result not kept; drain set never filled | Python docs, `asyncio.create_task` ("save a reference") |
| J2 | sync `requests` inside `async def` | asyncio docs, "running blocking code" |
| J3 | bare `except:` swallows `CancelledError` (timeouts and shutdown ignored) | Python 3.8 change to `CancelledError` (now a `BaseException`) |
| J4 | lambda in a loop closes over the loop variable | Python FAQ, late binding closures |
| J5 | naive `datetime.utcnow()` compared with aware datetimes | Python 3.12 deprecation of `utcnow` |
| L1 | money through `float` and `round()` (half-even, binary error) | `decimal` module docs |
| L2 | `str.lstrip("acct:")` strips a character set, not a prefix | PEP 616 (`removeprefix`) |
| L3 | `x or default` when `x` can be a falsy zero (`Money.__bool__`) | common falsy-zero bug |
| L4 | generator consumed twice | common |
| L5 | `lru_cache` on a value that changes (balance) | `functools` docs |
| D1 | check-then-insert race on a usage cap | Django docs, "avoiding race conditions" |
| D2 | `timezone.now().date()` (UTC) instead of `timezone.localdate()` | Django time zone docs |
| D4 | `AddField(default=0)` backfills existing rows before `AlterField(null=True)` | Django migrations docs |
| D5 | `|safe` on partner-supplied text | Django docs, automatic HTML escaping |
| H1 | `hash(str) % n` for partitioning: randomised per process | Python docs, `PYTHONHASHSEED` |
| H2 | `re.sub(p, r, s, re.IGNORECASE)`: the flag lands in `count` | Python 3.13 deprecation of positional `count` |
| H3 | `NOT IN (subquery)` that contains NULL is never true | SQL three-valued logic |
| H5 | `bool(os.environ.get(...))`: `"0"` is truthy | common config bug |
| H6 | `list.remove` while iterating the same list skips items | Python tutorial, "modifying a collection while iterating" |
| H8 | decorator without `functools.wraps`: Flask endpoint name clash | Flask docs, view decorators |
| H12 | callee changed from raising to returning None; an untouched caller relies on the exception | caller outside the diff |
| H13 | lazy generator returned from inside `with open(...)` | common |
| H16 | page count with `//` drops the last partial page | common |

## Layout and building

`<fixture>/main/` is the tree committed on `main`. Each `<fixture>/<dir>/` holds the full files that
a branch adds or replaces. `fixture.json` names the branches and their commit messages.
`../build_hard_fixtures.py OUTDIR` turns this into git repos with fixed dates. `../run_case.sh`
does this automatically, the first time it extracts fixtures.

The sources are plain files rather than a tarball, so every case can be read in a PR. Nothing in
the fixture code, comments or commit messages points at a planted bug.

## Running

```bash
JOBS=8 evals/run_hard.sh quick-v5 "/rk:quick"     # every hard case, scored table at the end
evals/score.py --suite quick-v5                   # rescore later
evals/run_case.sh py-jobs feature/concurrent-dispatch deep-jobs "/rk:deep"   # one case
evals/score.py evals/runs/deep-jobs/report.md py-jobs:feature/concurrent-dispatch
```

`score.py` reads only the final report text (the `result` in `stream.jsonl`, saved as
`report.md`), not run-folder files. It sorts each expected defect into **reported**,
**dismissed** (it appears only in a "not reported / dropped / dismissed" section) or **missed**.
A report that lists what its verifier threw away gets no credit for those items. On clean
cases, every critical, important or unrated finding block counts as a false alarm.
`status.json` records `seconds` (wall clock), `api_seconds`, `cost_usd` and `num_turns`.

## Checked

Every fixture's own test suite passes on every branch (pytest; Django `manage.py test`). That
is deliberate: the bugs are ones the authors' tests miss. Each planted bug was then triggered by
running the code. Some examples: `convert(10.50 USD @1.15)` gives 12.07, not 12.08.
`'acct:cash'` becomes `'sh'`. A symlink member is extracted and `/etc/hostname` is served. The
slug `acme-web/../../outside` writes outside the storage root. `claim()` raises "can't compare
offset-naive and offset-aware datetimes" after the first retry. `run()` returns with jobs still
claimed. Legacy kind `mail` runs `report.export`. Migrating an existing coupon leaves
`max_uses = 0`. In py-ingest, six separate worker processes put one tenant in six different
partitions, and `INGEST_DRY_RUN=0` turns dry run on.
