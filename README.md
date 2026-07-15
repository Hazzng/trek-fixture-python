# trek-fixture-python

A small Python fixture repository for the **Trek** autonomous engineering
platform spike. It contains a calculator library and a module-run HTTP server
backed by Redis (calculation cache) and Postgres (calculation history).

## Requirements

- Python 3.10+ (Python 3.12 recommended)
- A reachable Redis service
- A reachable Postgres service and an existing database

Redis and Postgres are **externally provisioned services**. The module server
does not start containers, install either service, or create service
credentials. Provision them separately (for example, through your local
platform, a development compose environment, or a managed development
instance), then give the server connection URLs through environment variables.
Do not commit credentials or production connection URLs to this repository.

## Install and test

Install the package and its development test dependency from the repository
root:

```bash
python -m pip install -e '.[dev]'
```

Run the test suite with:

```bash
pytest -q
```

The service-backed integration tests use the configured Redis and Postgres
services and skip their live checks when either service is unavailable. Unit
tests do not require either external service.

## Configure the external services

Set these variables before starting the server:

| Service | Preferred variable | Compatibility aliases | Default |
| --- | --- | --- | --- |
| Redis cache | `REDIS_URL` | `TREK_REDIS_URL` | `redis://127.0.0.1:6379/0` |
| Postgres history | `DATABASE_URL` | `POSTGRES_URL`, `TREK_POSTGRES_URL` | `postgresql://127.0.0.1:5432/postgres` |

The server uses the preferred variable when it is non-empty, then checks the
aliases from left to right, and finally uses the documented local default.
The defaults therefore expect Redis on `127.0.0.1:6379`, Redis database `0`,
and Postgres on `127.0.0.1:5432` with the `postgres` database. Set explicit
URLs when your provisioned services use different hosts, ports, databases, or
credentials. For example:

```bash
export REDIS_URL='redis://:secret@redis.example.test:6379/0'
export DATABASE_URL='postgresql://app:secret@postgres.example.test:5432/trek'
```

## Run the module server locally

With the external services running and their URLs configured, start the server
as a Python module:

```bash
python -m trek_fixture.server --host 127.0.0.1 --port 8000
```

The server listens at `http://127.0.0.1:8000`. Check connectivity to both
backends through the health endpoint:

```bash
curl http://127.0.0.1:8000/health
```

Submit a calculation with the operation and operands as query parameters (the
first request is computed and cached, while a repeat request can be served
from Redis):

```bash
curl 'http://127.0.0.1:8000/calculate?op=power&a=2&b=3'
```

The health response includes boolean `redis` and `postgres` reachability
fields. Read persisted calculations from Postgres as a top-level JSON list:

```bash
curl 'http://127.0.0.1:8000/history?limit=10'
```

Stop the local process with `Ctrl-C`. Stopping the module server does not stop
or remove the externally provisioned Redis or Postgres services.

## Layout

```
src/trek_fixture/   calculator, strings, and HTTP server modules
tests/              unit and service-backed integration tests
environment.json    runtime manifest seed (ADR-024)
```
