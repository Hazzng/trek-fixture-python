"""HTTP service for calculator operations, caching, and calculation history."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any, Protocol, cast

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from psycopg.rows import dict_row
from redis import Redis

from trek_fixture.calculator import add, divide, multiply, power, subtract


class CacheClient(Protocol):
    """The small Redis interface needed by the service."""

    def get(self, name: str) -> str | bytes | None: ...

    def setex(self, name: str, time: int, value: str) -> Any: ...


class CalculationRequest(BaseModel):
    """The operands and calculator operation supplied to ``/calculate``."""

    operation: str
    a: float
    b: float


DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_DATABASE_URL = "postgresql://localhost:5432/trek_fixture"


Operation = Callable[[float, float], float]
OPERATIONS: dict[str, Operation] = {
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
    "power": power,
}


class CalculationStore:
    """Persist calculation results in Redis and Postgres when configured.

    Both clients are optional so the HTTP server remains useful for local
    development without running infrastructure.  When a service is absent or
    temporarily unavailable, calculations continue and history is retained in
    a process-local fallback until the process exits.
    """

    def __init__(
        self,
        cache_client: CacheClient | None = None,
        connection_factory: Callable[[], Any] | None = None,
        history_enabled: bool | None = None,
        cache_ttl: int = 300,
    ) -> None:
        self.cache_client = cache_client
        if cache_client is None:
            redis_url = os.getenv("REDIS_URL") or DEFAULT_REDIS_URL
            self.cache_client = cast(
                CacheClient, Redis.from_url(redis_url, decode_responses=True)
            )

        database_url = (
            os.getenv("DATABASE_URL")
            or os.getenv("POSTGRES_URL")
            or DEFAULT_DATABASE_URL
        )
        self.connection_factory = connection_factory
        if self.connection_factory is None:
            self.connection_factory = lambda: psycopg.connect(
                database_url, row_factory=dict_row
            )
        self.history_enabled = (
            history_enabled
            if history_enabled is not None
            else self.connection_factory is not None
        )
        self.cache_ttl = cache_ttl
        self._fallback_history: list[dict[str, Any]] = []

    @staticmethod
    def _cache_key(request: CalculationRequest) -> str:
        return f"calculation:{request.operation}:{request.a}:{request.b}"

    def _cached_result(self, key: str) -> float | None:
        if self.cache_client is None:
            return None
        try:
            value = self.cache_client.get(key)
            if value is None:
                return None
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            payload = json.loads(value)
            return float(payload["result"])
        except Exception:
            return None

    def _cache_result(self, key: str, result: float) -> None:
        if self.cache_client is None:
            return
        try:
            self.cache_client.setex(
                key, self.cache_ttl, json.dumps({"result": result})
            )
        except Exception:
            return

    def _save_to_postgres(
        self, operation: str, a: float, b: float, result: float
    ) -> bool:
        if not self.history_enabled or self.connection_factory is None:
            return False
        try:
            with self.connection_factory() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS calculation_history (
                            id BIGSERIAL PRIMARY KEY,
                            operation TEXT NOT NULL,
                            a DOUBLE PRECISION NOT NULL,
                            b DOUBLE PRECISION NOT NULL,
                            result DOUBLE PRECISION NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cursor.execute(
                        """
                        INSERT INTO calculation_history (operation, a, b, result)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (operation, a, b, result),
                    )
                connection.commit()
        except Exception:
            return False
        return True

    def save_history(
        self, operation: str, a: float, b: float, result: float
    ) -> None:
        if not self._save_to_postgres(operation, a, b, result):
            self._fallback_history.append(
                {"operation": operation, "a": a, "b": b, "result": result}
            )

    def history(self) -> list[dict[str, Any]]:
        if self.history_enabled and self.connection_factory is not None:
            try:
                with self.connection_factory() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT operation, a, b, result
                            FROM calculation_history
                            ORDER BY created_at DESC, id DESC
                            """
                        )
                        rows = cursor.fetchall()
                    return [dict(row) for row in rows]
            except Exception:
                pass
        return list(self._fallback_history)

    def calculate(self, request: CalculationRequest) -> tuple[float, bool]:
        key = self._cache_key(request)
        cached = self._cached_result(key)
        if cached is not None:
            self.save_history(request.operation, request.a, request.b, cached)
            return cached, True

        operation = OPERATIONS.get(request.operation)
        if operation is None:
            raise ValueError(f"unsupported operation: {request.operation}")
        result = operation(request.a, request.b)
        self._cache_result(key, result)
        self.save_history(request.operation, request.a, request.b, result)
        return result, False


def create_app(store: CalculationStore | None = None) -> FastAPI:
    """Create an application, optionally with explicitly injected services."""

    calculation_store = store or CalculationStore()
    application = FastAPI(title="Trek Fixture Calculator API", version="0.1.0")

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    def calculate_request(request: CalculationRequest) -> dict[str, float | bool]:
        try:
            result, cached = calculation_store.calculate(request)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ZeroDivisionError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"result": result, "cached": cached}

    @application.post("/calculate")
    def calculate(request: CalculationRequest) -> dict[str, float | bool]:
        return calculate_request(request)

    @application.get("/calculate")
    def calculate_from_query(
        op: str, a: float, b: float
    ) -> dict[str, float | bool]:
        return calculate_request(CalculationRequest(operation=op, a=a, b=b))

    @application.get("/history")
    def history() -> list[dict[str, Any]]:
        return calculation_store.history()

    return application


app = create_app()


def main() -> None:
    """Run the service with Uvicorn when invoked as a Python module."""

    import uvicorn

    uvicorn.run(
        "trek_fixture.server:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
