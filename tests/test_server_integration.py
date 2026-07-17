"""Live integration coverage for the spawned calculator service.

Healthy-service URLs are supplied through dedicated test environment variables.
The module intentionally keeps Redis and PostgreSQL imports inside fixtures so
an offline collection of the normal test suite remains safe.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest


_URL_NAMES = {
    "redis": (
        "TEST_REDIS_URL",
        "REDIS_TEST_URL",
        "INTEGRATION_REDIS_URL",
    ),
    "postgres": (
        "TEST_DATABASE_URL",
        "TEST_POSTGRES_URL",
        "DATABASE_TEST_URL",
        "POSTGRES_TEST_URL",
        "INTEGRATION_DATABASE_URL",
    ),
}


@dataclass(frozen=True)
class ServiceUrls:
    redis: str
    postgres: str


def _dedicated_url(service: str) -> str | None:
    for name in _URL_NAMES[service]:
        value = os.getenv(name)
        if value:
            return value
    return None


def _healthy_urls() -> ServiceUrls | None:
    redis_url = _dedicated_url("redis")
    postgres_url = _dedicated_url("postgres")
    if redis_url is None or postgres_url is None:
        return None
    return ServiceUrls(redis=redis_url, postgres=postgres_url)


def _probe_healthy_services(urls: ServiceUrls) -> None:
    import psycopg
    import redis

    cache = redis.from_url(urls.redis, socket_connect_timeout=1)
    try:
        cache.ping()
    finally:
        cache.close()

    with psycopg.connect(urls.postgres, connect_timeout=2) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)


@pytest.fixture
def healthy_service_urls() -> ServiceUrls:
    """Return reachable dedicated endpoints or skip healthy live coverage."""

    urls = _healthy_urls()
    if urls is None:
        pytest.skip(
            "set TEST_REDIS_URL and TEST_DATABASE_URL for healthy live tests"
        )
    try:
        _probe_healthy_services(urls)
    except Exception as exc:  # service availability is an intentional skip
        pytest.skip(f"dedicated healthy services are unavailable: {exc}")
    return urls


@pytest.fixture
def clean_healthy_services(healthy_service_urls: ServiceUrls) -> ServiceUrls:
    """Clear only the dedicated test services before a stateful test."""

    import psycopg
    import redis

    cache = redis.from_url(healthy_service_urls.redis, socket_connect_timeout=1)
    try:
        cache.flushdb()
    finally:
        cache.close()

    with psycopg.connect(healthy_service_urls.postgres, connect_timeout=2) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS calculations")
        connection.commit()
    return healthy_service_urls


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method=method,
    )
    with urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read())


@contextmanager
def spawned_server(urls: ServiceUrls) -> Iterator[str]:
    """Run the actual module entry point against explicitly supplied services."""

    port = _free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "HOST": "127.0.0.1",
            "PORT": str(port),
            "REDIS_URL": urls.redis,
            "DATABASE_URL": urls.postgres,
            "PYTHONUNBUFFERED": "1",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "trek_fixture.server"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise AssertionError(f"server exited before becoming ready: {output}")
            try:
                _request(base_url, "/health")
                break
            except (URLError, ConnectionError, TimeoutError):
                time.sleep(0.1)
        else:
            raise AssertionError("spawned server did not become ready")
        yield base_url
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()


def _calculate(base_url: str, operation: str, a: int, b: int) -> dict[str, Any]:
    status, response = _request(
        base_url,
        "/calculate",
        method="POST",
        payload={"operation": operation, "a": a, "b": b},
    )
    assert status == 200
    return response


def test_healthy_spawned_server_reports_both_dependencies(
    clean_healthy_services: ServiceUrls,
) -> None:
    with spawned_server(clean_healthy_services) as base_url:
        status, response = _request(base_url, "/health")

    assert status == 200
    assert response == {"status": "ok", "redis": True, "postgres": True}


def test_degraded_spawned_server_reports_each_unreachable_dependency() -> None:
    """Synthetic invalid endpoints exercise degraded health without preflight."""

    unreachable = ServiceUrls(
        redis="redis://127.0.0.1:1/0",
        postgres="postgresql://127.0.0.1:1/postgres?connect_timeout=1",
    )
    with spawned_server(unreachable) as base_url:
        status, response = _request(base_url, "/health")

    assert status == 200
    assert response == {"status": "ok", "redis": False, "postgres": False}


def test_http_calculations_isolate_full_tuple_cache_identity(
    clean_healthy_services: ServiceUrls,
) -> None:
    expected = {
        ("power", 2, 10): 1024,
        ("add", 2, 10): 12,
        ("multiply", 2, 10): 20,
    }
    with spawned_server(clean_healthy_services) as base_url:
        first_results = {key: _calculate(base_url, *key) for key in expected}
        second_results = {key: _calculate(base_url, *key) for key in expected}

    for key, result in expected.items():
        assert first_results[key] == {
            "operation": key[0],
            "a": key[1],
            "b": key[2],
            "result": result,
            "cached": False,
        }
        assert second_results[key] == {
            "operation": key[0],
            "a": key[1],
            "b": key[2],
            "result": result,
            "cached": True,
        }
    assert {response["result"] for response in first_results.values()} == {
        1024,
        12,
        20,
    }


def test_history_persists_cached_requests_in_reverse_order(
    clean_healthy_services: ServiceUrls,
) -> None:
    requests = [
        ("add", 1, 2, 3),
        ("multiply", 3, 4, 12),
        ("power", 2, 5, 32),
    ]
    with spawned_server(clean_healthy_services) as base_url:
        for operation, a, b, _ in requests:
            _calculate(base_url, operation, a, b)
        for operation, a, b, _ in requests[:2]:
            cached = _calculate(base_url, operation, a, b)
            assert cached["cached"] is True

        status, response = _request(base_url, "/history?limit=5")

    assert status == 200
    records = response["history"]
    assert len(records) == 5
    expected = list(reversed(requests[:2])) + [requests[2], requests[1], requests[0]]
    for record, (operation, a, b, result) in zip(records, expected):
        assert record["operation"] == operation
        assert record["a"] == a
        assert record["b"] == b
        assert record["result"] == result
        assert record["at"]


def test_startup_creates_schema_and_restart_reuses_it(
    clean_healthy_services: ServiceUrls,
) -> None:
    with spawned_server(clean_healthy_services) as first_base_url:
        first = _calculate(first_base_url, "power", 2, 10)
        assert first["result"] == 1024
        status, first_history = _request(first_base_url, "/history?limit=5")
        assert status == 200
        assert first_history["history"]

    with spawned_server(clean_healthy_services) as second_base_url:
        status, second_history = _request(second_base_url, "/history?limit=5")

    assert status == 200
    assert second_history["history"][0]["result"] == 1024
