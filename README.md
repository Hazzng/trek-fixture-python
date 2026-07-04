# trek-fixture-python

A small, deterministic Python fixture repository for the **Trek** autonomous
engineering platform spike (Phase 0). It exists so the execution sandbox can
clone a real repo at a known ref and run its unit tests reproducibly.

First-pilot scope (doc 13): Python, deterministic local setup, good unit tests,
no production credentials, moderate size, branch protection on `main`,
low-risk tickets.

## Layout

```
src/trek_fixture/   calculator.py, strings.py
tests/              test_calculator.py, test_strings.py
environment.json    runtime manifest seed (ADR-024)
```

## Setup & test (deterministic)

```bash
pip install -e .[dev]   # pytest 8.3.4 is the only dependency
pytest -q               # all tests pass
```

Python 3.10+ (3.12 recommended).
# prtest
