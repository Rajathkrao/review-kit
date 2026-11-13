# assets service

Stores uploaded design assets per project and serves them back.

- Flask 3, Python 3.11 in production (see Dockerfile). Tests: `pytest -q`.
- Everything under STORAGE_ROOT is one directory per project slug. A project must never be able to
  read or write another project's directory, or anything outside STORAGE_ROOT.
- Specs for features live in `docs/`.
