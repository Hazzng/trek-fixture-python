"""Contract tests for the package HTTP server."""

from __future__ import annotations

import importlib
import json
import os
import tomllib
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _client(
    server: Any,
    redis: FakeRedis,
    postgres: FakePostgres,
) -> Any:
    """Build the application with deterministic dependency doubles."""
    from fastapi.testclient import TestClient

    app = server.create_app(redis_client=redis, postgres_factory=postgres)
    return TestClient(app)


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
    assert any(dependency.startswith("fastapi") for dependency in dependencies)
    assert any(dependency.startswith("uvicorn") for dependency in dependencies)
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

        history_response = client.get("/history?limit=2")
        assert history_response.status_code == 200
        history = history_response.json()
        assert len(history) == 2
        assert [entry["op"] for entry in history] == ["power", "multiply"]
        assert [entry["result"] for entry in history] == [1024, 6]
        assert all(set(entry) == {"op", "a", "b", "result", "at"} for entry in history)
        assert all(isinstance(entry["at"], str) and entry["at"] for entry in history)

        newest = client.get("/history?limit=1")
        assert newest.status_code == 200
        assert newest.json() == [history[0]]

    assert calls == ["add", "multiply", "power"]
    assert len(redis.set_keys) == 3
    assert len(postgres.history) == 3
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

    from fastapi.testclient import TestClient

    with TestClient(server.create_app()) as client:
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
