"""Contract tests for the production HTTP calculation service."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).parents[1]


class RecordingRedis:
    """Small Redis-shaped fake that records cache interactions."""

    def __init__(self) -> None:
        self.values: dict[Any, Any] = {}
        self.get_keys: list[Any] = []
        self.set_calls: list[tuple[Any, Any]] = []

    def get(self, key: Any) -> Any:
        self.get_keys.append(key)
        return self.values.get(key)

    def set(self, key: Any, value: Any, **_: Any) -> None:
        self.set_calls.append((key, value))
        self.values[key] = value


class RecordingCursor:
    def __init__(self, connection: "RecordingConnection") -> None:
        self.connection = connection
        self.rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, statement: str, parameters: Any = None) -> None:
        self.connection.statements.append((statement, parameters))
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("insert into calculations") and parameters is not None:
            self.connection.history.append(tuple(parameters))
        if normalized.startswith("select"):
            self.rows = list(self.connection.history)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class RecordingConnection:
    """Postgres-shaped fake for schema and history contract tests."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.history: list[tuple[Any, ...]] = []

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self)

    def commit(self) -> None:
        return None


def load_server() -> Any:
    """Load the service module while making its absence a real test failure."""

    spec = importlib.util.find_spec("trek_fixture.server")
    assert spec is not None, "trek_fixture.server must be an installable module"
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_routes_dispatch_through_calculator_and_persist_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = load_server()
    from trek_fixture import calculator

    calls: list[tuple[str, float, float]] = []

    def wrapped(name: str, result: float):
        def operation(a: float, b: float) -> float:
            calls.append((name, a, b))
            return result

        return operation

    monkeypatch.setattr(calculator, "add", wrapped("add", 5))
    monkeypatch.setattr(calculator, "multiply", wrapped("multiply", 6))
    monkeypatch.setattr(calculator, "power", wrapped("power", 8))

    redis = RecordingRedis()
    database = RecordingConnection()
    app = server.create_app(redis_client=redis, db_connection=database)
    client = app.test_client()

    health = client.get("/health")
    assert health.status_code == 200
    assert health.get_json() == {"status": "ok"}

    for operation, expected in (("add", 5), ("multiply", 6), ("power", 8)):
        response = client.post(
            "/calculate",
            json={"operation": operation, "a": 2, "b": 3},
        )
        assert response.status_code == 200
        assert response.get_json()["result"] == expected

    assert calls == [("add", 2, 3), ("multiply", 2, 3), ("power", 2, 3)]

    history = client.get("/history")
    assert history.status_code == 200
    assert len(history.get_json()["history"]) == 3


def test_calculate_uses_same_tuple_identity_for_redis_cache() -> None:
    server = load_server()
    redis = RecordingRedis()
    database = RecordingConnection()
    client = server.create_app(
        redis_client=redis,
        db_connection=database,
    ).test_client()

    first = client.post(
        "/calculate", json={"operation": "add", "a": 4, "b": 9}
    )
    second = client.post(
        "/calculate", json={"operation": "add", "a": 4, "b": 9}
    )

    assert first.status_code == second.status_code == 200
    assert first.get_json() == second.get_json()
    assert len(redis.set_calls) == 1
    assert len(redis.get_keys) == 2
    assert redis.get_keys[0] == redis.get_keys[1]
    key = redis.get_keys[0]
    assert isinstance(key, tuple)
    assert key == ("add", 4, 9)
    assert len(database.history) == 1


def test_startup_schema_is_idempotent_and_supports_history() -> None:
    server = load_server()
    database = RecordingConnection()

    first_client = server.create_app(
        redis_client=RecordingRedis(),
        db_connection=database,
    ).test_client()
    second_client = server.create_app(
        redis_client=RecordingRedis(),
        db_connection=database,
    ).test_client()

    ddl = " ".join(statement for statement, _ in database.statements).lower()
    assert ddl.count("create table if not exists calculations") == 2
    for column in ("operation", "operand_a", "operand_b", "result"):
        assert column in ddl

    response = second_client.post(
        "/calculate", json={"operation": "power", "a": 2, "b": 4}
    )
    assert response.status_code == 200
    assert first_client.get("/history").get_json()["history"]


def test_runtime_defaults_and_dependencies_are_declared() -> None:
    server = load_server()
    assert server.DEFAULT_REDIS_URL == "redis://localhost:6379"
    assert server.DEFAULT_DATABASE_URL == "postgresql://localhost:5432/postgres"

    pyproject = (ROOT / "pyproject.toml").read_text().lower()
    assert "redis" in pyproject
    assert "psycopg" in pyproject or "postgres" in pyproject


def test_environment_manifest_and_readme_document_local_launch() -> None:
    environment_text = (ROOT / "environment.json").read_text().lower()
    readme_text = (ROOT / "README.md").read_text().lower()

    for text in (environment_text, readme_text):
        assert "python -m trek_fixture.server" in text
        assert "redis_url" in text
        assert "database_url" in text
        assert "redis://localhost:6379" in text
        assert "postgresql://localhost:5432/postgres" in text

    assert "separately" in readme_text
    assert "docker-compose" in readme_text or "docker compose" in readme_text
    json.loads((ROOT / "environment.json").read_text())
