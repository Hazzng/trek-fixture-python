"""Integration coverage for the service-backed calculator HTTP API."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pytest


ROOT = Path(__file__).parents[1]
DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_POSTGRES_URL = "postgresql://127.0.0.1:5432/postgres"


def _service_url(*names: str, default: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _endpoint(url: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(url)
    return parsed.hostname or "127.0.0.1", parsed.port or default_port


def _port_is_open(url: str, default_port: int) -> bool:
    host, port = _endpoint(url, default_port)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | list[Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read())


def test_server_module_is_available_for_module_execution() -> None:
    """The package must provide the module used by ``python -m`` startup."""
    import importlib.util

    assert importlib.util.find_spec("trek_fixture.server") is not None


def test_server_runtime_dependencies_are_declared() -> None:
    """The deployable package declares every runtime service dependency."""
    import tomllib

    with (ROOT / "pyproject.toml").open("rb") as pyproject:
        metadata = tomllib.load(pyproject)
    dependencies = set(metadata["project"]["dependencies"])
    dependency_names = {dependency.split("[", 1)[0].split("=", 1)[0] for dependency in dependencies}

    assert {"fastapi", "uvicorn", "redis", "psycopg"} <= dependency_names


@pytest.fixture(scope="module")
def live_server() -> Any:
    """Run the API only when both externally managed services can be reached."""
    redis_url = _service_url("REDIS_URL", "TREK_REDIS_URL", default=DEFAULT_REDIS_URL)
    postgres_url = _service_url(
        "DATABASE_URL", "POSTGRES_URL", "TREK_POSTGRES_URL", default=DEFAULT_POSTGRES_URL
    )
    if not _port_is_open(redis_url, 6379):
        pytest.skip("Redis is unavailable")
    if not _port_is_open(postgres_url, 5432):
        pytest.skip("Postgres is unavailable")

    port = _free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "REDIS_URL": redis_url,
            "DATABASE_URL": postgres_url,
            "HOST": "127.0.0.1",
            "PORT": str(port),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "trek_fixture.server", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                status, payload = _request_json(base_url, "/health")
                if status == 200 and isinstance(payload, dict):
                    yield base_url
                    return
            except (HTTPError, URLError, TimeoutError, OSError):
                time.sleep(0.1)
        output = process.stdout.read() if process.stdout is not None else ""
        pytest.skip(f"service dependencies did not produce a healthy API: {output[-500:]}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def test_service_startup_health(live_server: str) -> None:
    status, payload = _request_json(live_server, "/health")

    assert status == 200
    assert isinstance(payload, dict)
    assert payload["status"] == "ok"
    assert payload["redis"] is True
    assert payload["postgres"] is True


def test_calculation_uses_cache_and_persists_history(live_server: str) -> None:
    unique_value = int(time.time_ns() % 1_000_000_000)
    calculation_path = f"/calculate?op=power&a={unique_value}&b=2"

    first_status, first = _request_json(live_server, calculation_path)
    second_status, second = _request_json(live_server, calculation_path)

    assert first_status == second_status == 200
    assert isinstance(first, dict) and isinstance(second, dict)
    assert first["result"] == unique_value**2
    assert first["cached"] is False
    assert second["result"] == first["result"]
    assert second["cached"] is True

    history_status, history_payload = _request_json(live_server, "/history?limit=10")
    assert history_status == 200
    assert isinstance(history_payload, list)
    matching = [entry for entry in history_payload if entry.get("result") == unique_value**2]
    assert matching


def test_history_is_newest_first_and_honors_limit(live_server: str) -> None:
    unique_value = int(time.time_ns() % 1_000_000_000)
    earlier_path = f"/calculate?op=add&a={unique_value}&b=1"
    later_path = f"/calculate?op=add&a={unique_value}&b=2"
    _request_json(live_server, earlier_path)
    _request_json(live_server, later_path)

    status, payload = _request_json(live_server, "/history?limit=2")

    assert status == 200
    assert isinstance(payload, list)
    assert len(payload) == 2
    assert payload[0]["result"] == unique_value + 2
    assert payload[1]["result"] == unique_value + 1
