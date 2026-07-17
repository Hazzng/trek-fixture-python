"""Production HTTP service for calculator operations.

The service deliberately keeps calculation semantics in :mod:`calculator`.
Redis is used as a result cache and PostgreSQL stores the calculation history.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from flask import Flask, jsonify, request
import psycopg
import redis

from trek_fixture import calculator

DEFAULT_REDIS_URL = "redis://localhost:6379"
DEFAULT_DATABASE_URL = "postgresql://localhost:5432/postgres"

_OPERATION_NAMES = {"add", "multiply", "power"}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS calculations (
    id BIGSERIAL PRIMARY KEY,
    operation TEXT NOT NULL,
    operand_a DOUBLE PRECISION NOT NULL,
    operand_b DOUBLE PRECISION NOT NULL,
    result DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def initialize_schema(connection: Any) -> None:
    """Create the history table if needed, making startup safe to repeat."""

    with connection.cursor() as cursor:
        cursor.execute(_SCHEMA)
    connection.commit()


def _dispatch(operation: str, a: float, b: float) -> float:
    """Dispatch every supported operation to the canonical calculator module."""

    # Build this map at call time so applications can decorate or instrument
    # calculator functions without creating a second implementation here.
    operations: dict[str, Callable[[float, float], float]] = {
        "add": calculator.add,
        "multiply": calculator.multiply,
        "power": calculator.power,
    }
    return operations[operation](a, b)


def _portable_cache_key(key: tuple[str, float, float]) -> str:
    """Encode a tuple key for Redis clients that only accept scalar keys."""

    return json.dumps(key, separators=(",", ":"))


def _cache_get(client: Any, key: tuple[str, float, float]) -> Any:
    """Read a tuple-keyed value, adapting real Redis' scalar-key restriction."""

    try:
        return client.get(key)
    except (TypeError, redis.exceptions.DataError):
        return client.get(_portable_cache_key(key))


def _cache_set(client: Any, key: tuple[str, float, float], value: str) -> None:
    """Write a tuple-keyed value, adapting real Redis' scalar-key restriction."""

    try:
        client.set(key, value)
    except (TypeError, redis.exceptions.DataError):
        client.set(_portable_cache_key(key), value)


def _cached_response(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        parsed = json.loads(value)
    elif isinstance(value, dict):
        parsed = value
    else:
        return None
    return parsed if isinstance(parsed, dict) else None


def _persist_calculation(
    connection: Any,
    operation: str,
    a: float,
    b: float,
    result: float,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO calculations (operation, operand_a, operand_b, result)
            VALUES (%s, %s, %s, %s)
            """,
            (operation, a, b, result),
        )
    connection.commit()


def _history(connection: Any) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT operation, operand_a, operand_b, result
            FROM calculations
            ORDER BY id
            """
        )
        rows = cursor.fetchall()
    return [
        {
            "operation": row[0],
            "a": row[1],
            "b": row[2],
            "result": row[3],
        }
        for row in rows
    ]


def create_app(
    redis_client: Any | None = None,
    db_connection: Any | None = None,
    *,
    redis_url: str | None = None,
    database_url: str | None = None,
) -> Flask:
    """Build the service, initializing its database schema before serving."""

    configured_redis_url = redis_url or os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
    configured_database_url = database_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL
    cache = redis_client or redis.from_url(configured_redis_url)
    database = db_connection or psycopg.connect(configured_database_url)
    initialize_schema(database)

    app = Flask(__name__)

    @app.get("/health")
    def health() -> Any:
        return jsonify(status="ok")

    @app.post("/calculate")
    def calculate() -> Any:
        payload = request.get_json(silent=True) or {}
        operation = payload.get("operation")
        a = payload.get("a")
        b = payload.get("b")
        if operation not in _OPERATION_NAMES or isinstance(a, bool) or isinstance(b, bool):
            return jsonify(error="operation, a, and b are required"), 400
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return jsonify(error="operation, a, and b are required"), 400

        key = (operation, a, b)
        cached = _cached_response(_cache_get(cache, key))
        if cached is not None:
            return jsonify(cached)

        try:
            result = _dispatch(operation, a, b)
        except (ArithmeticError, ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400
        response = {"operation": operation, "a": a, "b": b, "result": result}
        _cache_set(cache, key, json.dumps(response))
        _persist_calculation(database, operation, a, b, result)
        return jsonify(response)

    @app.get("/history")
    def history() -> Any:
        return jsonify(history=_history(database))

    return app


def main() -> None:
    """Connect to configured services and run the local HTTP server."""

    app = create_app()
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
    )


if __name__ == "__main__":
    main()
