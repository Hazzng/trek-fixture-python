"""HTTP API for the service-backed calculator fixture.

Redis and Postgres are intentionally external services.  The application only
creates its small history table; provisioning and credentials remain outside
this package.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from typing import Any

import psycopg  # type: ignore[import-not-found]
import redis  # type: ignore[import-not-found]
import uvicorn  # type: ignore[import-not-found]
from fastapi import FastAPI, HTTPException, Query  # type: ignore[import-not-found]
from psycopg.rows import dict_row  # type: ignore[import-not-found]

from trek_fixture.calculator import add, divide, multiply, power, subtract

DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_DATABASE_URL = "postgresql://127.0.0.1:5432/postgres"

Operation = Callable[[float, float], float]
OPERATIONS: dict[str, Operation] = {
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
    "power": power,
}



def _service_url(*names: str, default: str) -> str:
    """Return the first non-empty configured service URL."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


class ServiceStore:
    """Small adapter around the Redis cache and Postgres history table."""

    def __init__(self, redis_url: str, database_url: str) -> None:
        self.redis: Any = redis.Redis.from_url(redis_url, decode_responses=True)
        self.database_url = database_url

    @staticmethod
    def _cache_key(operation: str, a: float, b: float) -> str:
        return f"trek_fixture:calculation:{operation}:{a!r}:{b!r}"

    def health(self) -> tuple[bool, bool]:
        """Check both service connections without changing application data."""
        try:
            redis_ok = bool(self.redis.ping())
        except Exception:
            redis_ok = False

        try:
            with psycopg.connect(self.database_url) as connection:
                connection.execute("SELECT 1")
            postgres_ok = True
        except Exception:
            postgres_ok = False
        return redis_ok, postgres_ok

    def _ensure_history_table(self, connection: Any) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS calculation_history (
                id BIGSERIAL PRIMARY KEY,
                operation TEXT NOT NULL,
                a DOUBLE PRECISION NOT NULL,
                b DOUBLE PRECISION NOT NULL,
                result DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def calculate(
        self, operation: str, a: float, b: float, function: Operation
    ) -> tuple[float, bool]:
        """Calculate, cache, and persist a result, returning ``(result, cached)``."""
        cache_key = self._cache_key(operation, a, b)
        cached_value = self.redis.get(cache_key)
        if cached_value is None:
            result = function(a, b)
            self.redis.set(cache_key, json.dumps(result))
            cached = False
        else:
            result = float(json.loads(cached_value))
            cached = True

        with psycopg.connect(self.database_url) as connection:
            self._ensure_history_table(connection)
            connection.execute(
                """
                INSERT INTO calculation_history (operation, a, b, result)
                VALUES (%s, %s, %s, %s)
                """ ,
                (operation, a, b, result),
            )
        return result, cached

    def history(self, limit: int) -> list[dict[str, Any]]:
        """Return the newest persisted calculations first."""
        with psycopg.connect(self.database_url) as connection:
            self._ensure_history_table(connection)
            rows = connection.execute(
                """
                SELECT operation, a, b, result, created_at
                FROM calculation_history
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
                row_factory=dict_row,
            ).fetchall()
        return [dict(row) for row in rows]


store = ServiceStore(
    _service_url("REDIS_URL", "TREK_REDIS_URL", default=DEFAULT_REDIS_URL),
    _service_url(
        "DATABASE_URL", "POSTGRES_URL", "TREK_POSTGRES_URL", default=DEFAULT_DATABASE_URL
    ),
)
app = FastAPI(title="Trek Fixture Calculator")


@app.get("/health")
def health() -> dict[str, bool | str]:
    """Report whether Redis and Postgres are reachable."""
    redis_ok, postgres_ok = store.health()
    return {
        "status": "ok" if redis_ok and postgres_ok else "degraded",
        "redis": redis_ok,
        "postgres": postgres_ok,
    }


@app.get("/calculate")
def calculate(
    op: str = Query(..., description="add, subtract, multiply, divide, or power"),
    a: float = Query(...),
    b: float = Query(...),
) -> dict[str, float | bool | str]:
    """Calculate an operation selected by query parameters."""
    function = OPERATIONS.get(op)
    if function is None:
        raise HTTPException(status_code=400, detail=f"unsupported operation: {op}")
    try:
        result, cached = store.calculate(op, a, b, function)
    except ZeroDivisionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="service unavailable") from error
    return {"operation": op, "a": a, "b": b, "result": result, "cached": cached}


@app.get("/history")
def history(
    limit: int = Query(10, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Return the newest calculation history entries as a top-level list."""
    try:
        return store.history(limit)
    except Exception as error:
        raise HTTPException(status_code=503, detail="service unavailable") from error


def main() -> None:
    """Run the API as ``python -m trek_fixture.server``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PORT", "8000"))
    )
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
