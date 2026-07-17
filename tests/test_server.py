"""Live HTTP API tests for the calculator server.

The endpoint tests use only the standard-library HTTP client so they exercise
an actual listening server.  Redis and PostgreSQL are preflighted and the
whole live fixture skips when either configured service is unavailable.
"""

from __future__ import annotations

from contextlib import closing
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

import pytest


DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"


def _server_module_available() -> bool:
    """Return whether the package has a server module without importing it."""
    return importlib.util.find_spec("trek_fixture.server") is not None


def _service_urls() -> tuple[str, str]:
    redis_url = os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)
    database_url = os.environ.get("DATABASE_URL") or os.environ.get(
        "POSTGRES_URL", DEFAULT_DATABASE_URL
    )
    return redis_url, database_url


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_request(
    port: int, path: str, **params: object
) -> tuple[int, dict[str, Any] | list[dict[str, Any]]]:
    query = urlencode({key: str(value) for key, value in params.items()})
    request = Request(f"http://127.0.0.1:{port}{path}?{query}")
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))
    with response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _connect_live_services(redis_url: str, database_url: str) -> tuple[Any, Any]:
    """Connect to both dependencies, skipping this module when unavailable."""
    redis = pytest.importorskip("redis")
    try:
        postgres = importlib.import_module("psycopg")
    except ModuleNotFoundError:
        postgres = pytest.importorskip("psycopg2")

    redis_client = redis.Redis.from_url(redis_url)
    try:
        redis_client.ping()
        database = postgres.connect(database_url)
        with database.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as error:
        redis_client.close()
        pytest.skip(f"Redis/PostgreSQL unavailable: {error}")
    return redis_client, database


@pytest.fixture(scope="module")
def live_server() -> Iterator[dict[str, Any]]:
    """Start the package server against the configured live services."""
    if not _server_module_available():
        pytest.skip("trek_fixture.server is not implemented yet")

    redis_url, database_url = _service_urls()
    redis_client, database = _connect_live_services(redis_url, database_url)
    port = _free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "REDIS_URL": redis_url,
            "DATABASE_URL": database_url,
            "HOST": "127.0.0.1",
            "PORT": str(port),
            "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "trek_fixture.server"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            redis_client.close()
            database.close()
            raise AssertionError(
                f"server exited during startup\nstdout={stdout}\nstderr={stderr}"
            )
        try:
            status, payload = _json_request(port, "/health")
        except (URLError, TimeoutError, OSError):
            time.sleep(0.1)
            continue
        if status == 200 and payload == {
            "status": "ok",
            "redis": True,
            "postgres": True,
        }:
            break
        time.sleep(0.1)
    else:
        process.terminate()
        stdout, stderr = process.communicate(timeout=3)
        redis_client.close()
        database.close()
        raise AssertionError(
            f"server did not become healthy\nstdout={stdout}\nstderr={stderr}"
        )

    try:
        yield {
            "port": port,
            "redis": redis_client,
            "database": database,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        redis_client.close()
        database.close()


@pytest.fixture
def unique_calculation(live_server: dict[str, Any]) -> Iterator[tuple[int, int]]:
    """Provide unique operands and remove only this test's own observations."""
    base = int(uuid.uuid4().hex[:8], 16)
    operands = (base, base + 1)
    yield operands
    database = live_server["database"]
    with database.cursor() as cursor:
        cursor.execute(
            "DELETE FROM calculations WHERE a = %s AND b = %s",
            operands,
        )
    database.commit()
    marker = str(base).encode()
    redis = live_server["redis"]
    for key in redis.scan_iter():
        if marker in key:
            redis.delete(key)


def _history_rows(database: Any) -> list[tuple[Any, ...]]:
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT op, a, b, result, at FROM calculations ORDER BY at DESC, id DESC"
        )
        return list(cursor.fetchall())


def test_server_module_provides_http_entrypoint() -> None:
    """The package must expose a runnable HTTP server module."""
    assert _server_module_available(), "trek_fixture.server module is missing"
    server = importlib.import_module("trek_fixture.server")
    assert callable(getattr(server, "main", None))


def test_health_reports_independent_service_connectivity(
    live_server: dict[str, Any],
) -> None:
    status, payload = _json_request(live_server["port"], "/health")
    assert status == 200
    assert payload == {"status": "ok", "redis": True, "postgres": True}


def test_calculate_reuses_operations_and_caches_results(
    live_server: dict[str, Any],
) -> None:
    port = live_server["port"]
    first_status, first = _json_request(port, "/calculate", op="power", a=2, b=10)
    second_status, second = _json_request(port, "/calculate", op="power", a=2, b=10)
    add_status, add_result = _json_request(port, "/calculate", op="add", a=7, b=5)
    multiply_status, multiply_result = _json_request(
        port, "/calculate", op="multiply", a=7, b=5
    )

    assert first_status == second_status == add_status == multiply_status == 200
    assert first == {"op": "power", "a": 2, "b": 10, "result": 1024, "cached": False}
    assert second == {"op": "power", "a": 2, "b": 10, "result": 1024, "cached": True}
    assert add_result["result"] == 12
    assert add_result["cached"] is False
    assert multiply_result["result"] == 84
    assert multiply_result["cached"] is False


def test_accepted_calculations_persist_even_when_cached(
    live_server: dict[str, Any], unique_calculation: tuple[int, int]
) -> None:
    base, next_value = unique_calculation
    port = live_server["port"]
    first_status, first = _json_request(
        port, "/calculate", op="add", a=base, b=next_value
    )
    second_status, second = _json_request(
        port, "/calculate", op="add", a=base, b=next_value
    )

    assert first_status == second_status == 200
    assert first["cached"] is False
    assert second["cached"] is True
    matching = [
        row
        for row in _history_rows(live_server["database"])
        if row[0] == "add" and row[1] == base and row[2] == next_value
    ]
    assert len(matching) == 2
    assert all(row[3] == base + next_value and row[4] is not None for row in matching)


def test_history_is_newest_first_and_honors_limits(
    live_server: dict[str, Any], unique_calculation: tuple[int, int]
) -> None:
    base, next_value = unique_calculation
    port = live_server["port"]
    for operation, a, b in (
        ("add", base, next_value),
        ("multiply", base, next_value),
        ("power", 2, 3),
    ):
        status, _ = _json_request(port, "/calculate", op=operation, a=a, b=b)
        assert status == 200

    history_by_limit: dict[int, list[dict[str, Any]]] = {}
    for limit in (1, 2, 5):
        status, payload = _json_request(port, "/history", limit=limit)
        assert status == 200
        assert isinstance(payload, list)
        assert len(payload) <= limit
        assert all({"op", "a", "b", "result", "at"} <= set(row) for row in payload)
        history_by_limit[limit] = payload

    assert history_by_limit[1] == history_by_limit[2][:1]
    assert history_by_limit[2] == history_by_limit[5][:2]
    assert history_by_limit[5] == history_by_limit[5][:5]
    timestamps = [str(row["at"]) for row in history_by_limit[5]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_rejected_inputs_have_no_cache_or_history_side_effect(
    live_server: dict[str, Any],
) -> None:
    port = live_server["port"]
    redis = live_server["redis"]
    database = live_server["database"]
    before_keys = tuple(sorted((key, redis.get(key)) for key in redis.scan_iter()))
    before_count = len(_history_rows(database))

    invalid_requests = (
        {"op": "unsupported", "a": 2, "b": 3},
        {"op": "add", "b": 3},
        {"op": "add", "a": 2},
        {"op": "add", "a": "not-a-number", "b": 3},
        {"op": "add", "a": 2, "b": "not-a-number"},
    )
    for query in invalid_requests:
        status, _ = _json_request(port, "/calculate", **query)
        assert 400 <= status < 500

    after_keys = tuple(sorted((key, redis.get(key)) for key in redis.scan_iter()))
    after_count = len(_history_rows(database))
    assert after_keys == before_keys
    assert after_count == before_count
