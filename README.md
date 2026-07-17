# trek-fixture-python

A small, deterministic Python fixture repository for the **Trek** autonomous
engineering platform spike. It provides a calculator HTTP service backed by
Redis for result caching and PostgreSQL for calculation history.

## Layout

```
src/trek_fixture/   calculator.py, server.py, strings.py
tests/              calculator, server, and strings tests
environment.json    runtime manifest seed (ADR-024)
```

## Install

Python 3.10+ is required (Python 3.12 is recommended). Create an environment
and install the package with its development test dependency:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

The server declares the Redis and PostgreSQL client libraries as runtime
dependencies. The `dev` extra pins pytest to 8.3.4.

## Run locally

The full service requires Redis and PostgreSQL to be running independently of
this repository. Start both services using your operating system's service
manager or local installations; this project does **not** provide Docker Compose orchestration.

By default, the server connects to:

- Redis at `redis://localhost:6379/0`
- PostgreSQL at `postgresql://localhost:5432/postgres`

The PostgreSQL database must already exist, and the configured user must be
able to create the `calculations` table. The server creates that table on
startup when PostgreSQL is reachable.

If your services use different hosts, ports, credentials, or databases, set
the connection URLs before starting the server:

```bash
export REDIS_URL='redis://localhost:6379/0'
export DATABASE_URL='postgresql://localhost:5432/postgres'
python -m trek_fixture.server
```

`python -m trek_fixture.server` starts the HTTP server on `127.0.0.1:8000`.
The other supported server settings are `HOST` (default `127.0.0.1`) and
`PORT` (default `8000`):

```bash
HOST=0.0.0.0 PORT=8080 python -m trek_fixture.server
```

Check service connectivity and use the API with requests such as:

```bash
curl http://127.0.0.1:8000/health
curl 'http://127.0.0.1:8000/calculate?op=add&a=2&b=3'
curl 'http://127.0.0.1:8000/history?limit=20'
```

`/health` reports whether Redis and PostgreSQL are reachable. Redis caches
calculation results, while PostgreSQL stores the calculation history.

## Run tests

Run the complete test suite from the repository root:

```bash
python -m pytest -q
```

The server tests are safe to run without local services; tests that require
reachable Redis or PostgreSQL are skipped when those services are unavailable.
For the complete service-backed behavior, start both services and configure
`REDIS_URL` and `DATABASE_URL` before running the tests.
