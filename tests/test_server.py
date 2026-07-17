"""Contract tests for the package HTTP server."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import io
import json
import os
import tomllib
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from wsgiref.util import setup_testing_defaults

import pytest


ROOT = Path(__file__).parent.parent


def _load_server() -> Any:
    """Load the server module with a test-friendly missing-feature failure."""
    try:
        return importlib.import_module("trek_fixture.server")
    except ModuleNotFoundError as exc:
        pytest.fail(f"the package HTTP server is not available: {exc}")


class FakeRedis:
    """Small Redis double that records cache operations and supports ping."""

    def __init__(self, *, reachable: bool = True) -> None:
        self.reachable = reachable
        self.values: dict[str, str] = {}
        self.set_keys: list[str] = []

    def ping(self) -> bool:
        if not self.reachable:
            raise ConnectionError("Redis is unavailable")
        return True

    def get(self, key: str) -> str | None:
        if not self.reachable:
            raise ConnectionError("Redis is unavailable")
        return self.values.get(key)

    def set(self, key: str, value: str, **_: Any) -> bool:
        if not self.reachable:
            raise ConnectionError("Redis is unavailable")
        self.values[key] = value
        self.set_keys.append(key)
        return True


class FakePostgresConnection:
    """Postgres double supporting schema, health, and history statements."""

    def __init__(self, history: list[tuple[Any, ...]]) -> None:
        self.history = history
        self.statements: list[str] = []
        self._rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> FakePostgresConnection:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def cursor(self) -> FakePostgresConnection:
        return self

    def execute(self, statement: str, parameters: Sequence[Any] = ()) -> None:
        self.statements.append(statement)
        normalized = statement.upper()
        if "INSERT" in normalized:
            values = tuple(parameters)
            if len(values) == 4:
                values += (datetime.now(timezone.utc),)
            self.history.append(values)
        elif "SELECT" in normalized and "CALCULATIONS" in normalized:
            rows = list(reversed(self.history))
            if parameters and isinstance(parameters[-1], int):
                rows = rows[: parameters[-1]]
            self._rows = rows

    def fetchone(self) -> tuple[int]:
        return (1,)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def commit(self) -> None:
        return None


class FakePostgres:
    """Callable connection factory matching the server's injected database hook."""

    def __init__(self, *, reachable: bool = True) -> None:
        self.reachable = reachable
        self.history: list[tuple[Any, ...]] = []
        self.connections: list[FakePostgresConnection] = []

    def __call__(self, _: str) -> FakePostgresConnection:
        if not self.reachable:
            raise ConnectionError("Postgres is unavailable")
        connection = FakePostgresConnection(self.history)
        self.connections.append(connection)
        return connection


class _Response:
    """Minimal response shape shared by the standard-library HTTP adapter."""

    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return json.loads(self._body)


class _CallableHTTPClient:
    """Exercise WSGI or ASGI applications without a framework test client."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def __enter__(self) -> _CallableHTTPClient:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def get(self, url: str) -> _Response:
        if inspect.iscoroutinefunction(self.app.__call__):
            return asyncio.run(self._asgi_get(url))
        return self._wsgi_get(url)

    def _wsgi_get(self, url: str) -> _Response:
        parsed = urlsplit(url)
        environ: dict[str, Any] = {}
        setup_testing_defaults(environ)
        environ.update(
            {
                "REQUEST_METHOD": "GET",
                "PATH_INFO": parsed.path,
                "QUERY_STRING": parsed.query,
                "wsgi.input": io.BytesIO(),
            }
        )
        status = "500 Internal Server Error"
        response_headers: list[tuple[str, str]] = []

        def start_response(value: str, headers: list[tuple[str, str]], *_: Any) -> None:
            nonlocal status, response_headers
            status = value
            response_headers = headers

        body = b"".join(self.app(environ, start_response))
        del response_headers
        return _Response(int(status.split()[0]), body)

    async def _asgi_get(self, url: str) -> _Response:
        parsed = urlsplit(url)
        messages: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        await self.app(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": parsed.path,
                "raw_path": parsed.path.encode(),
                "query_string": parsed.query.encode(),
                "headers": [(b"host", b"testserver")],
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
            },
            receive,
            send,
        )
        start = next(message for message in messages if message["type"] == "http.response.start")
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return _Response(start["status"], body)


def _http_client(app: Any) -> Any:
    """Build an HTTP test client without prescribing the server framework."""
    if hasattr(app, "test_client"):
        return app.test_client()
    if callable(app):
        return _CallableHTTPClient(app)
    pytest.fail("create_app must return a testable HTTP application")


def _client(
    server: Any,
    redis: FakeRedis,
    postgres: FakePostgres,
) -> Any:
    """Build the application with deterministic dependency doubles."""
    return _http_client(server.create_app(redis_client=redis, postgres_factory=postgres))


def _assert_health(response: Any, *, redis: bool, postgres: bool) -> None:
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "redis": redis,
        "postgres": postgres,
    }


def test_runtime_dependencies_and_local_configuration_are_declared() -> None:
    """The package and README expose the complete local server contract."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = {dependency.lower() for dependency in project["project"]["dependencies"]}
    assert any(dependency.startswith("redis") for dependency in dependencies)
    assert any(dependency.startswith("psycopg") for dependency in dependencies)

    readme = (ROOT / "README.md").read_text()
    assert "python -m trek_fixture.server" in readme
    assert "REDIS_URL" in readme
    assert "redis://localhost:6379" in readme
    assert "DATABASE_URL" in readme
    assert "postgresql://localhost:5432/postgres" in readme
    assert "docker-compose" in readme.lower()


def test_calculate_routes_dispatch_cache_and_persist_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP calculations use calculator operations, Redis caching, and history."""
    server = _load_server()
    from trek_fixture import calculator

    calls: list[str] = []
    for operation in ("add", "multiply", "power"):
        original = getattr(calculator, operation)

        def record_call(
            a: float,
            b: float,
            *,
            _operation: str = operation,
            _original: Callable[[float, float], float] = original,
        ) -> float:
            calls.append(_operation)
            return _original(a, b)

        monkeypatch.setattr(calculator, operation, record_call)

    redis = FakeRedis()
    postgres = FakePostgres()
    with _client(server, redis, postgres) as client:
        for operation, expected in (("add", 5), ("multiply", 6), ("power", 1024)):
            first = client.get(f"/calculate?op={operation}&a=2&b={'10' if operation == 'power' else '3'}")
            assert first.status_code == 200
            assert first.json() == {"result": expected, "cached": False}

            second = client.get(
                f"/calculate?op={operation}&a=2&b={'10' if operation == 'power' else '3'}"
            )
            assert second.status_code == 200
            assert second.json() == {"result": expected, "cached": True}

        history_response = client.get("/history?limit=6")
        assert history_response.status_code == 200
        history = history_response.json()
        assert len(history) == 6
        assert [entry["op"] for entry in history] == [
            "power",
            "power",
            "multiply",
            "multiply",
            "add",
            "add",
        ]
        assert [entry["result"] for entry in history] == [1024, 1024, 6, 6, 5, 5]
        assert all(set(entry) == {"op", "a", "b", "result", "at"} for entry in history)
        assert all(isinstance(entry["at"], str) and entry["at"] for entry in history)

        newest = client.get("/history?limit=1")
        assert newest.status_code == 200
        assert newest.json() == [history[0]]

    assert calls == ["add", "multiply", "power"]
    assert len(redis.set_keys) == 3
    assert len(postgres.history) == 6
    assert any(
        "CREATE TABLE" in statement.upper()
        for connection in postgres.connections
        for statement in connection.statements
    )


def test_health_reports_complete_status_for_live_dependencies() -> None:
    """Healthy dependency probes return the complete HTTP 200 JSON contract."""
    server = _load_server()
    with _client(server, FakeRedis(), FakePostgres()) as client:
        response = client.get("/health")

    _assert_health(response, redis=True, postgres=True)


def test_health_keeps_serving_when_redis_is_unreachable() -> None:
    """A Redis outage does not hide a reachable Postgres dependency."""
    server = _load_server()
    with _client(server, FakeRedis(reachable=False), FakePostgres()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["redis"] is False
    assert response.json()["postgres"] is True
    assert response.json()["status"] in {"ok", "degraded"}


def test_health_keeps_serving_when_postgres_is_unreachable() -> None:
    """A Postgres startup/schema failure does not stop health responses."""
    server = _load_server()
    with _client(server, FakeRedis(), FakePostgres(reachable=False)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["redis"] is True
    assert response.json()["postgres"] is False
    assert response.json()["status"] in {"ok", "degraded"}


def _value_is_result(value: Any, expected: float) -> bool:
    """Accept the JSON or string representation used by a Redis cache."""
    if isinstance(value, bytes):
        value = value.decode()
    try:
        return float(json.loads(value)) == expected
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def test_real_services_exercise_http_cache_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reachable Redis/Postgres provide an end-to-end API and persistence check."""
    server = _load_server()
    redis_module = pytest.importorskip("redis")
    psycopg = pytest.importorskip("psycopg")
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://localhost:5432/postgres"
    )

    real_redis = redis_module.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        real_redis.ping()
    except Exception as exc:
        pytest.skip(f"Redis is not reachable at {redis_url}: {exc}")

    try:
        connection = psycopg.connect(database_url, connect_timeout=1)
        connection.close()
    except Exception as exc:
        pytest.skip(f"Postgres is not reachable at {database_url}: {exc}")

    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("DATABASE_URL", database_url)
    token = f"{uuid.uuid4().int % 1_000_000_000}.{uuid.uuid4().int % 1000}"
    a = float(token)
    b = 7.0
    before_keys = set(real_redis.scan_iter())

    with _http_client(server.create_app()) as client:
        health = client.get("/health")
        _assert_health(health, redis=True, postgres=True)

        for operation, expected in (("add", a + b), ("multiply", a * b), ("power", a**b)):
            first = client.get(f"/calculate?op={operation}&a={a}&b={b}")
            assert first.status_code == 200
            assert first.json() == {"result": expected, "cached": False}
            second = client.get(f"/calculate?op={operation}&a={a}&b={b}")
            assert second.status_code == 200
            assert second.json() == {"result": expected, "cached": True}

        history_response = client.get("/history?limit=10")
        assert history_response.status_code == 200
        matching = [
            entry
            for entry in history_response.json()
            if entry["a"] == a and entry["b"] == b
        ]
        assert [entry["op"] for entry in matching[:3]] == ["power", "multiply", "add"]
        assert all(set(entry) == {"op", "a", "b", "result", "at"} for entry in matching[:3])

    after_keys = set(real_redis.scan_iter())
    new_keys = after_keys - before_keys
    assert any(
        _value_is_result(real_redis.get(key), a + b)
        or _value_is_result(real_redis.get(key), a * b)
        or _value_is_result(real_redis.get(key), a**b)
        for key in new_keys
    )
