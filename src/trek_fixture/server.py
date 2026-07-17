"""Runnable HTTP calculator service with optional Redis and PostgreSQL backing."""

from __future__ import annotations

from datetime import datetime
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from decimal import Decimal
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

from .calculator import add, multiply, power

REDIS_DEFAULT = "redis://localhost:6379/0"
DATABASE_DEFAULT = "postgresql://localhost:5432/postgres"
_CACHE_NAMESPACE = uuid.uuid4().hex

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calculations (
    id BIGSERIAL PRIMARY KEY,
    op TEXT NOT NULL,
    a NUMERIC NOT NULL,
    b NUMERIC NOT NULL,
    result NUMERIC NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", REDIS_DEFAULT)


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DATABASE_DEFAULT)


def _redis_connection() -> Any:
    import redis

    return redis.Redis.from_url(
        _redis_url(),
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def _postgres_connection() -> Any:
    import psycopg

    return psycopg.connect(_database_url(), connect_timeout=1)


def _redis_reachable() -> bool:
    try:
        client = _redis_connection()
        try:
            client.ping()
            return True
        finally:
            client.close()
    except Exception:
        return False


def _ensure_schema(connection: Any) -> None:
    connection.execute(_SCHEMA)


def _postgres_reachable() -> bool:
    try:
        with _postgres_connection() as connection:
            _ensure_schema(connection)
        return True
    except Exception:
        return False


def _initialize_schema() -> None:
    """Create the history table when PostgreSQL is available.

    A failed optional dependency must not prevent the HTTP process from
    starting; health reports the current state independently on each request.
    """
    try:
        with _postgres_connection() as connection:
            _ensure_schema(connection)
    except Exception:
        return


def _cache_key(operation: str, a: int | float, b: int | float) -> str:
    payload = json.dumps([operation, a, b], separators=(",", ":"), allow_nan=False)
    return f"trek-fixture:{_CACHE_NAMESPACE}:calculation:" + payload


def _calculate(operation: str, a: int | float, b: int | float) -> tuple[int | float, bool]:
    functions = {"add": add, "multiply": multiply, "power": power}
    try:
        calculate = functions[operation]
    except KeyError as exc:
        raise ValueError(f"unsupported operation: {operation}") from exc

    key = _cache_key(operation, a, b)
    result: int | float | None = None
    cached = False
    try:
        client = _redis_connection()
        try:
            cached_value = client.get(key)
            if cached_value is not None:
                parsed_value = json.loads(cached_value)
                if isinstance(parsed_value, (int, float)) and not isinstance(parsed_value, bool):
                    result = parsed_value
                    cached = True
        finally:
            client.close()
    except Exception:
        result = None

    if result is None:
        result = calculate(a, b)
        try:
            client = _redis_connection()
            try:
                client.set(key, json.dumps(result, allow_nan=False))
            finally:
                client.close()
        except Exception:
            pass

    _record_calculation(operation, a, b, result)
    return result, cached


def _record_calculation(
    operation: str, a: int | float, b: int | float, result: int | float
) -> None:
    try:
        with _postgres_connection() as connection:
            _ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO calculations (op, a, b, result)
                VALUES (%s, %s, %s, %s)
                """,
                (operation, a, b, result),
            )
    except Exception:
        return


def _json_number(value: Any) -> int | float:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def _history(limit: int) -> list[dict[str, Any]]:
    try:
        with _postgres_connection() as connection:
            _ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT op, a, b, result, at
                FROM calculations
                ORDER BY at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
    except Exception:
        return []

    return [
        {
            "op": str(operation),
            "a": _json_number(a),
            "b": _json_number(b),
            "result": _json_number(result),
            "at": at.isoformat() if isinstance(at, datetime) else str(at),
        }
        for operation, a, b, result, at in rows
    ]


def _query_number(query: dict[str, list[str]], name: str) -> int | float:
    values = query.get(name)
    if not values or not values[0]:
        raise ValueError(f"missing parameter: {name}")
    raw_value = values[0]
    try:
        return int(raw_value)
    except ValueError:
        return float(raw_value)


class CalculatorHandler(BaseHTTPRequestHandler):
    """Handle the small JSON HTTP API."""

    server_version = "trek-fixture/0.1"

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                self._send_json(
                    {
                        "status": "ok",
                        "redis": _redis_reachable(),
                        "postgres": _postgres_reachable(),
                    }
                )
            elif parsed.path == "/calculate":
                operation = query.get("op", [""])[0]
                a = _query_number(query, "a")
                b = _query_number(query, "b")
                result, cached = _calculate(operation, a, b)
                self._send_json({"result": result, "cached": cached})
            elif parsed.path == "/history":
                raw_limit = query.get("limit", ["20"])[0]
                limit = max(0, min(int(raw_limit), 100))
                self._send_json(_history(limit))
            else:
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, TypeError, OverflowError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    """Initialize optional storage and return a configured HTTP server."""
    _initialize_schema()
    resolved_host = host if host is not None else os.environ.get("HOST", "127.0.0.1")
    resolved_port = port if port is not None else int(os.environ.get("PORT", "8000"))
    return ThreadingHTTPServer((resolved_host, resolved_port), CalculatorHandler)


def main() -> None:
    server = create_server()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
