"""Contract and guarded integration tests for the calculator HTTP server."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest


REDIS_DEFAULT = "redis://localhost:6379/0"
DATABASE_DEFAULT = "postgresql://postgres:postgres@localhost:5432/postgres"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=1) as response:
        assert response.status == 200
        return json.load(response)


def _start_server(redis_url: str, database_url: str) -> tuple[subprocess.Popen[str], str]:
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "REDIS_URL": redis_url,
            "DATABASE_URL": database_url,
            "HOST": "127.0.0.1",
            "PORT": str(port),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "trek_fixture.server"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr else ""
            assert process.returncode is None, (
                "server exited before becoming available; stderr: " + stderr
            )
        try:
            _get_json(base_url + "/health")
            return process, base_url
        except (OSError, urllib.error.URLError, TimeoutError):
            time.sleep(0.05)
    process.terminate()
    assert False, "server did not answer /health after startup"


def _stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def _live_clients() -> tuple[Any, Any, str, str]:
    try:
        import psycopg
        import redis
    except ImportError as exc:
        pytest.skip(f"optional live-service client unavailable: {exc}")

    redis_url = os.environ.get("REDIS_URL", REDIS_DEFAULT)
    database_url = os.environ.get("DATABASE_URL", DATABASE_DEFAULT)
    try:
        redis_client = redis.Redis.from_url(redis_url, socket_connect_timeout=1)
        redis_client.ping()
        with psycopg.connect(database_url, connect_timeout=1):
            pass
    except Exception as exc:
        pytest.skip(f"Redis/PostgreSQL live services unavailable: {exc}")
    return redis_client, psycopg, redis_url, database_url


@pytest.fixture(scope="module")
def live_server() -> Iterator[tuple[str, Any, Any]]:
    redis_client, psycopg, redis_url, database_url = _live_clients()
    process, base_url = _start_server(redis_url, database_url)
    try:
        yield base_url, psycopg, database_url
    finally:
        _stop_server(process)
        redis_client.close()


def test_runtime_dependencies_are_declared() -> None:
    """The server's Redis and PostgreSQL drivers are runtime dependencies."""
    import tomllib

    project_file = Path(__file__).parents[1] / "pyproject.toml"
    with project_file.open("rb") as stream:
        project = tomllib.load(stream)
    dependencies = [str(dependency).lower() for dependency in project["project"]["dependencies"]]
    assert any(dependency.startswith("redis") for dependency in dependencies)
    assert any(dependency.startswith("psycopg") for dependency in dependencies)


def test_unreachable_dependencies_do_not_prevent_health() -> None:
    """An unavailable dependency degrades health without preventing startup."""
    process, base_url = _start_server(
        "redis://127.0.0.1:1/0",
        "postgresql://127.0.0.1:1/unreachable",
    )
    try:
        assert _get_json(base_url + "/health") == {
            "status": "ok",
            "redis": False,
            "postgres": False,
        }
    finally:
        _stop_server(process)


def test_health_reports_both_reachable_dependencies(live_server: tuple[str, Any, Any]) -> None:
    base_url, _, _ = live_server
    assert _get_json(base_url + "/health") == {
        "status": "ok",
        "redis": True,
        "postgres": True,
    }


def test_startup_creates_orderable_calculations_schema(
    live_server: tuple[str, Any, Any],
) -> None:
    _, psycopg, database_url = live_server
    with psycopg.connect(database_url) as connection:
        columns = connection.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'calculations'
            """
        ).fetchall()
    by_name = {str(name): str(data_type) for name, data_type in columns}
    assert {"id", "op", "a", "b", "result", "at"} <= by_name.keys()
    assert by_name["id"] in {"bigint", "integer"}
    assert by_name["op"] in {"text", "character varying"}
    assert by_name["a"] in {"numeric", "real", "double precision"}
    assert by_name["b"] in {"numeric", "real", "double precision"}
    assert by_name["result"] in {"numeric", "real", "double precision"}
    assert by_name["at"] in {"timestamp with time zone", "timestamp without time zone"}


def test_calculate_caches_and_persists_cache_hits(
    live_server: tuple[str, Any, Any],
) -> None:
    base_url, psycopg, database_url = live_server
    a = time.time_ns() % 1_000_000_000
    query = urllib.parse.urlencode({"op": "add", "a": a, "b": 17})
    first = _get_json(base_url + "/calculate?" + query)
    second = _get_json(base_url + "/calculate?" + query)
    assert first["result"] == a + 17
    assert first["cached"] is False
    assert second["result"] == a + 17
    assert second["cached"] is True

    with psycopg.connect(database_url) as connection:
        count = connection.execute(
            "SELECT count(*) FROM calculations WHERE op = %s AND a = %s AND b = %s",
            ("add", a, 17),
        ).fetchone()[0]
    assert count == 2

    for operation, left, right, expected in (
        ("multiply", 6, 7, 42),
        ("power", 2, 10, 1024),
    ):
        params = urllib.parse.urlencode({"op": operation, "a": left, "b": right})
        response = _get_json(base_url + "/calculate?" + params)
        assert response["result"] == expected
        assert response["cached"] is False


def test_history_is_newest_first_with_stable_tie_breaking_and_limit(
    live_server: tuple[str, Any, Any],
) -> None:
    base_url, psycopg, database_url = live_server
    timestamp = datetime.now(timezone.utc)
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "DELETE FROM calculations WHERE op = %s AND a IN (%s, %s)",
            ("history-tie", 901.0, 902.0),
        )
        connection.execute(
            """
            INSERT INTO calculations (op, a, b, result, at)
            VALUES (%s, %s, %s, %s, %s), (%s, %s, %s, %s, %s)
            """,
            (
                "history-tie",
                901.0,
                1.0,
                901.0,
                timestamp,
                "history-tie",
                902.0,
                1.0,
                902.0,
                timestamp,
            ),
        )

    history = _get_json(base_url + "/history?limit=5")
    assert isinstance(history, list)
    assert len(history) <= 5
    assert history[0]["result"] == 902
    assert history[1]["result"] == 901
    assert {"op", "a", "b", "result", "at"} <= history[0].keys()

    generated_results = []
    for value in range(1000, 1007):
        params = urllib.parse.urlencode({"op": "add", "a": value, "b": 0})
        generated_results.append(_get_json(base_url + "/calculate?" + params)["result"])
    limited = _get_json(base_url + "/history?limit=5")
    assert len(limited) == 5
    assert [item["result"] for item in limited] == generated_results[-1:-6:-1]
