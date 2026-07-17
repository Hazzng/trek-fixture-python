# trek-fixture-python

A small Python fixture repository for the **Trek** autonomous engineering
platform spike. It includes a calculator library and a production-style HTTP
service that dispatches calculations through that library.

## Layout

```
src/trek_fixture/   calculator.py, server.py, strings.py
tests/              calculator, server, and strings tests
environment.json    runtime manifest seed (ADR-024)
```

## Setup & test

```bash
pip install -e .[dev]
pytest -q
```

Python 3.10+ (3.12 recommended). The editable install declares Flask, Redis,
and PostgreSQL (psycopg) as runtime dependencies.

## Run the HTTP service locally

Start Redis and Postgres separately before launching the service; this project
does not use docker-compose (or Docker Compose) to manage them. The defaults
are suitable for local services:

```bash
export REDIS_URL=redis://localhost:6379
export DATABASE_URL=postgresql://localhost:5432/postgres
python -m trek_fixture.server
```

`REDIS_URL` and `DATABASE_URL` are optional and may point to other service
instances. On startup the service creates the `calculations` history table if
it does not already exist. It provides `GET /health`, `POST /calculate` with
`{"operation":"add|multiply|power", "a": 2, "b": 3}`, and `GET /history`.
