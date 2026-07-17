"""Contract tests for the package HTTP server."""

from __future__ import annotations

import importlib
import tomllib
from collections.abc import Callable
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

    def __enter__(self) -> FakePostgresConnection:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def cursor(self) -> FakePostgresConnection:
        return self

    def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> None:
        self.statements.append(statement)
        if "INSERT" in statement.upper():
            self.history.append(parameters)

    def fetchone(self) -> tuple[int]:
        return (1,)

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

    assert calls == ["add", "multiply", "power"]
    assert len(redis.set_keys) == 3
    assert len(postgres.history) == 3
    assert any("CREATE TABLE" in statement.upper() for connection in postgres.connections for statement in connection.statements)


def test_health_reports_both_live_dependencies() -> None:
    """Healthy dependency probes return HTTP 200 and independent booleans."""
    server = _load_server()
    with _client(server, FakeRedis(), FakePostgres()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["redis"] is True
    assert response.json()["postgres"] is True


def test_health_keeps_serving_when_redis_is_unreachable() -> None:
    """A Redis outage does not hide a reachable Postgres dependency."""
    server = _load_server()
    with _client(server, FakeRedis(reachable=False), FakePostgres()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["redis"] is False
    assert response.json()["postgres"] is True


def test_health_keeps_serving_when_postgres_is_unreachable() -> None:
    """A Postgres startup/schema failure does not stop health responses."""
    server = _load_server()
    with _client(server, FakeRedis(), FakePostgres(reachable=False)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["redis"] is True
    assert response.json()["postgres"] is False
