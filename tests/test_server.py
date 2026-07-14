"""Tests for the HTTP calculation service."""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from trek_fixture.server import CalculationStore, create_app


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls = 0

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def setex(self, key: str, _seconds: int, value: str) -> None:
        self.set_calls += 1
        self.values[key] = value


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((query, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.cursor_obj = FakeCursor(rows)
        self.commits = 0

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self, **_kwargs: object) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1


def test_health_endpoint() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_calculate_uses_redis_result_cache() -> None:
    redis = FakeRedis()
    store = CalculationStore(cache_client=redis)
    client = TestClient(create_app(store))
    payload = {"operation": "power", "a": 2, "b": 3}

    first = client.post("/calculate", json=payload)
    second = client.post("/calculate", json=payload)

    assert first.status_code == 200
    assert first.json() == {"result": 8, "cached": False}
    assert second.status_code == 200
    assert second.json() == {"result": 8, "cached": True}
    assert redis.set_calls == 1


def test_calculate_records_and_reads_postgres_history() -> None:
    rows = [{"operation": "add", "a": 2, "b": 3, "result": 5}]
    connection = FakeConnection(rows)
    store = CalculationStore(
        connection_factory=lambda: connection,
        history_enabled=True,
    )
    client = TestClient(create_app(store))

    response = client.post(
        "/calculate", json={"operation": "add", "a": 2, "b": 3}
    )
    history = client.get("/history")

    assert response.status_code == 200
    assert history.status_code == 200
    assert history.json() == rows
    assert connection.commits == 1
    assert any("INSERT INTO calculation_history" in query for query, _ in connection.cursor_obj.executed)


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_SERVICE_TESTS") != "1",
    reason="set RUN_LIVE_SERVICE_TESTS=1 to run Redis/Postgres integration tests",
)
def test_live_services() -> None:
    """Exercise configured services, while remaining a clean offline skip."""
    pytest.importorskip("redis")
    pytest.importorskip("psycopg")
    client = TestClient(create_app())

    assert client.get("/health").status_code == 200
    response = client.post(
        "/calculate", json={"operation": "multiply", "a": 6, "b": 7}
    )
    assert response.status_code == 200
    assert client.get("/history").status_code == 200
