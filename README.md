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

Pint is a runtime dependency and is installed from the package metadata. The
editable development install also includes the pinned pytest development
dependency:

```bash
pip install -e .[dev]
pytest -q
```

Python 3.10+ (3.12 recommended).

## Calculator usage

`trek_fixture.calculator` provides a module-owned Pint registry, numeric unit
conversion, and addition of compatible quantities:

```python
from trek_fixture.calculator import add, convert, ureg

feet = convert(1, "meter", "foot")
total = add(1 * ureg.meter, 1 * ureg.foot)
total_in_meters = total.to("meter").magnitude
```

`feet` is approximately `3.28084`, and `total_in_meters` is approximately
`1.3048`. Pint raises a dimensionality error when incompatible quantities are
added.
