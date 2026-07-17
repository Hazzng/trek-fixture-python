"""Production HTTP service for calculator operations.

The service deliberately keeps calculation semantics in :mod:`calculator`.
Redis is used as a result cache and PostgreSQL stores the calculation history.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

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
    operand_a NUMERIC NOT NULL,
    operand_b NUMERIC NOT NULL,
    result NUMERIC NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
_MIGRATE_NUMERIC_SCHEMA = """
ALTER TABLE calculations
    ALTER COLUMN operand_a TYPE NUMERIC USING operand_a::NUMERIC,
    ALTER COLUMN operand_b TYPE NUMERIC USING operand_b::NUMERIC,
    ALTER COLUMN result TYPE NUMERIC USING result::NUMERIC
"""


def initialize_schema(connection: Any) -> None:
    """Create the history table and preserve exact numeric values on upgrades."""

    with connection.cursor() as cursor:
        cursor.execute(_SCHEMA)
        cursor.execute(_MIGRATE_NUMERIC_SCHEMA)
    connection.commit()


def _dispatch(operation: str, a: int | float, b: int | float) -> Any:
    """Dispatch every supported operation to the canonical calculator module."""

    # Build this map at call time so applications can decorate or instrument
    # calculator functions without creating a second implementation here.
    operations: dict[str, Callable[[int | float, int | float], Any]] = {
        "add": calculator.add,
        "multiply": calculator.multiply,
        "power": calculator.power,
    }
    return operations[operation](a, b)


def _portable_cache_key(key: tuple[str, int | float, int | float]) -> str:
    """Encode a tuple key for Redis clients that only accept scalar keys."""

    return json.dumps(key, separators=(",", ":"))


def _cache_get(client: Any, key: tuple[str, int | float, int | float]) -> Any:
    """Read a tuple-keyed value, adapting real Redis' scalar-key restriction."""

    try:
        return client.get(key)
    except (TypeError, redis.exceptions.DataError):
        return client.get(_portable_cache_key(key))


def _cache_set(client: Any, key: tuple[str, int | float, int | float], value: str) -> None:
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


def _is_finite_number(value: Any) -> bool:
    """Return whether a request operand is representable as JSON data."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    # Integers are exact and have no non-finite values; converting them to a
    # float here would reject or round otherwise valid large operands.
    if isinstance(value, int):
        return True
    return math.isfinite(value)


def _parse_query_number(value: Any) -> Any:
    """Parse query numbers without losing precision for integer operands."""

    if not isinstance(value, str):
        return value
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _strict_json(value: Any) -> None:
    """Reject values such as NaN and Infinity that JSON does not define."""

    json.dumps(value, allow_nan=False)


def _numeric_parameter(value: int | float) -> Decimal:
    """Adapt JSON numbers to PostgreSQL NUMERIC without integer narrowing."""

    return Decimal(value) if isinstance(value, int) else Decimal(str(value))


def _json_number(value: Any) -> Any:
    """Convert PostgreSQL NUMERIC results to JSON's integer/float types."""

    if not isinstance(value, Decimal):
        return value
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _persist_calculation(
    connection: Any,
    operation: str,
    a: int | float,
    b: int | float,
    result: int | float,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO calculations (operation, operand_a, operand_b, result)
            VALUES (%s, %s, %s, %s)
            """,
            (
                operation,
                _numeric_parameter(a),
                _numeric_parameter(b),
                _numeric_parameter(result),
            ),
        )
    connection.commit()


def _history(connection: Any, limit: int) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT operation, operand_a, operand_b, result, created_at
            FROM calculations
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cursor.fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        record = {
            "op": row[0],
            "a": _json_number(row[1]),
            "b": _json_number(row[2]),
            "result": _json_number(row[3]),
        }
        if len(row) > 4:
            at = row[4]
            record["at"] = at.isoformat() if hasattr(at, "isoformat") else at
        records.append(record)
    return records


def _dependency_health(cache: Any, database: Any | None) -> tuple[bool, bool]:
    """Probe Redis and PostgreSQL independently without making health fatal."""

    try:
        cache.ping()
    except Exception:
        redis_ok = False
    else:
        redis_ok = True

    if database is None:
        return redis_ok, False
    try:
        with database.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return redis_ok, False
    return redis_ok, True


def _supports_live_metadata(cache: Any) -> bool:
    """Identify real Redis clients while retaining compatibility with test doubles."""

    return callable(getattr(cache, "ping", None))


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
    database = db_connection
    if database is None:
        try:
            database = psycopg.connect(configured_database_url)
        except Exception:
            database = None
    if database is not None:
        try:
            initialize_schema(database)
        except Exception:
            database = None

    app = Flask(__name__)
    live_metadata = _supports_live_metadata(cache)

    @app.get("/health")
    def health() -> Any:
        if not live_metadata:
            return jsonify(status="ok")
        redis_ok, postgres_ok = _dependency_health(cache, database)
        return jsonify(status="ok", redis=redis_ok, postgres=postgres_ok)

    @app.route("/calculate", methods=["GET", "POST"])
    def calculate() -> Any:
        payload = request.get_json(silent=True) or {}
        if request.method == "GET":
            payload = request.args
        operation = payload.get("op" if request.method == "GET" else "operation")
        # Keep accepting the POST spelling for GET callers during migration, but
        # make the documented GET query parameter (`op`) the canonical one.
        if request.method == "GET" and operation is None:
            operation = payload.get("operation")
        a = payload.get("a")
        b = payload.get("b")
        if request.method == "GET":
            a = _parse_query_number(a)
            b = _parse_query_number(b)
        if operation not in _OPERATION_NAMES or isinstance(a, bool) or isinstance(b, bool):
            return jsonify(error="operation, a, and b are required"), 400
        if not _is_finite_number(a) or not _is_finite_number(b):
            return jsonify(error="operation, a, and b are required"), 400
        operation_name = str(operation)
        a_value = cast(int | float, a)
        b_value = cast(int | float, b)

        key = (operation_name, a_value, b_value)
        try:
            cached = _cached_response(_cache_get(cache, key))
        except Exception:
            return jsonify(error="redis is unavailable"), 503
        if cached is not None:
            try:
                _strict_json(cached.get("result"))
            except (ValueError, TypeError):
                return jsonify(error="cached result is not valid JSON"), 502
            if database is None and live_metadata:
                return jsonify(error="postgres is unavailable"), 503
            if live_metadata:
                _persist_calculation(database, operation_name, a_value, b_value, cached["result"])
                cached["cached"] = True
            if request.method == "GET":
                return jsonify(result=cached["result"], cached=True)
            return jsonify(cached)

        try:
            result = _dispatch(operation_name, a_value, b_value)
            # Validate the calculator result before handing it to Flask, Redis,
            # or PostgreSQL; complex values and non-finite numbers are not valid
            # JSON API results.
            _strict_json(result)
        except (ArithmeticError, ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400
        response = {
            "operation": operation_name,
            "a": a_value,
            "b": b_value,
            "result": result,
        }
        if live_metadata:
            response["cached"] = False
        try:
            _cache_set(cache, key, json.dumps(response, allow_nan=False))
        except Exception:
            return jsonify(error="redis is unavailable"), 503
        if database is None:
            return jsonify(error="postgres is unavailable"), 503
        _persist_calculation(database, operation_name, a_value, b_value, result)
        if request.method == "GET":
            return jsonify(result=result, cached=False)
        return jsonify(response)

    @app.get("/history")
    def history() -> Any:
        if database is None:
            return jsonify(error="postgres is unavailable"), 503
        raw_limit = request.args.get("limit", "100")
        try:
            limit = max(1, min(int(raw_limit), 1000))
        except ValueError:
            return jsonify(error="limit must be an integer"), 400
        return jsonify(_history(database, limit))

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
