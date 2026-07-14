# trek-fixture-python

A small Python calculator and runnable HTTP service for the **Trek** autonomous
engineering platform spike. The service keeps the calculator module as the
single operation boundary and adds optional Redis result caching and Postgres
calculation history.

## Layout

```
src/trek_fixture/calculator.py  deterministic calculator operations
src/trek_fixture/server.py      FastAPI application and Uvicorn entry point
tests/                          unit and opt-in live-service tests
environment.json                runtime and service metadata
```

## Setup and tests

Python 3.10+ is supported (3.12 recommended). Install the application and
its development test tools in a virtual environment:

```bash
python -m pip install -e '.[dev]'
pytest -q
ruff check src tests
mypy src/trek_fixture/server.py
```

The live-service test is intentionally opt-in and skips when run offline:

```bash
RUN_LIVE_SERVICE_TESTS=1 pytest -m integration -q
```

## Run the HTTP API locally

The API starts without external services; in that mode results are calculated
normally, history is kept in memory, and caching is disabled. To use the
backends, start Redis and Postgres locally and set their connection URLs:

```bash
export REDIS_URL='redis://localhost:6379/0'
export DATABASE_URL='postgresql://localhost:5432/trek_fixture'
uvicorn trek_fixture.server:app --reload
```

The server also supports `python -m trek_fixture.server`. `HOST` defaults to
`127.0.0.1` and `PORT` defaults to `8000`.

### Endpoints

Check readiness:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

Calculate with one of `add`, `subtract`, `multiply`, `divide`, or `power`:

```bash
curl -X POST http://127.0.0.1:8000/calculate \
  -H 'content-type: application/json' \
  -d '{"operation":"power","a":2,"b":8}'
# {"result":256.0,"cached":false}
```

A repeat request with the same operation and operands returns `cached: true`
when Redis is available. Calculation history is available at:

```bash
curl http://127.0.0.1:8000/history
```

When Postgres is configured, the service creates the
`calculation_history` table on first write and stores each calculation's
operation, operands, result, and timestamp. Redis uses a five-minute result
TTL. Backend connection failures do not prevent the health endpoint or the
calculator from serving local requests.
