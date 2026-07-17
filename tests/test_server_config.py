"""Contract tests for the lightweight HTTP server entry point."""

from __future__ import annotations

import importlib
import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

import pytest


DEFAULT_REDIS_URL = "redis://localhost:6379"
DEFAULT_DATABASE_URL = "postgresql://localhost:5432/postgres"


def _load_server():
    """Load the server module as a test assertion rather than a collection error."""
    try:
        return importlib.import_module("trek_fixture.server")
    except ModuleNotFoundError as exc:
        pytest.fail(f"the server entry point is missing: {exc}")


@contextmanager
def _running_server() -> Iterator[str]:
    server = _load_server()
    httpd = server.create_server(host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        httpd.server_close()


def _get_json(base_url: str, path: str, **query: object) -> tuple[int, dict[str, object]]:
    query_string = urlencode({key: str(value) for key, value in query.items()})
    with urlopen(f"{base_url}{path}?{query_string}", timeout=2) as response:
        return response.status, json.load(response)


def _can_connect(url: str, default_port: int) -> bool:
    parsed = urlsplit(url)
    if parsed.hostname is None:
        return False
    port = parsed.port or default_port
    try:
        with socket.create_connection((parsed.hostname, port), timeout=0.5):
            return True
    except (OSError, ValueError):
        return False


def test_server_uses_exact_default_dependency_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    server = importlib.reload(_load_server())

    assert server.REDIS_URL == DEFAULT_REDIS_URL
    assert server.DATABASE_URL == DEFAULT_DATABASE_URL


def test_server_reads_dependency_urls_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_url = "redis://cache.example:6380/2"
    database_url = "postgresql://db.example:5433/app"
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("DATABASE_URL", database_url)
    server = importlib.reload(_load_server())

    assert server.REDIS_URL == redis_url
    assert server.DATABASE_URL == database_url


def test_health_endpoint_reports_both_dependencies() -> None:
    server = _load_server()
    if not (
        _can_connect(server.REDIS_URL, 6379)
        and _can_connect(server.DATABASE_URL, 5432)
    ):
        pytest.skip("requires reachable Redis and Postgres endpoints")

    with _running_server() as base_url:
        status, body = _get_json(base_url, "/health")

    assert status == 200
    assert body == {"status": "ok", "redis": True, "postgres": True}


def test_calculate_endpoint_routes_operations_and_returns_cache_flag() -> None:
    with _running_server() as base_url:
        add_status, add_body = _get_json(base_url, "/calculate", op="add", a=2, b=3)
        multiply_status, multiply_body = _get_json(
            base_url, "/calculate", op="multiply", a=6, b=7
        )
        power_status, power_body = _get_json(
            base_url, "/calculate", op="power", a=2, b=10
        )
        repeat_status, repeat_body = _get_json(
            base_url, "/calculate", op="add", a=2, b=3
        )

    assert add_status == multiply_status == power_status == repeat_status == 200
    assert add_body["result"] == 5
    assert multiply_body["result"] == 42
    assert power_body["result"] == 1024
    assert isinstance(add_body["cached"], bool)
    assert isinstance(multiply_body["cached"], bool)
    assert isinstance(power_body["cached"], bool)
    assert repeat_body["result"] == add_body["result"]
    assert repeat_body["cached"] is True


def test_readme_documents_server_invocation_and_dependency_defaults() -> None:
    readme = Path(__file__).parents[1] / "README.md"
    contents = readme.read_text(encoding="utf-8")

    assert "python -m trek_fixture.server" in contents
    assert f"REDIS_URL={DEFAULT_REDIS_URL}" in contents
    assert f"DATABASE_URL={DEFAULT_DATABASE_URL}" in contents
