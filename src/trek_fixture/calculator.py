"""A minimal, well-tested calculator module."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from openpyxl import Workbook  # type: ignore[import-untyped]


def add(a: float, b: float) -> float:
    """Return the sum of two numbers."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return the difference of two numbers."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of two numbers."""
    return a * b


def divide(a: float, b: float) -> float:
    """Return the quotient of two numbers.

    Raises:
        ZeroDivisionError: if ``b`` is zero.
    """
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a / b


def export_xlsx(path: str | Path, results: Iterable[dict[str, Any]]) -> None:
    """Write calculation results to a genuine .xlsx workbook."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Results"

    rows = list(results)
    if not rows:
        workbook.save(Path(path))
        return

    headers = list(rows[0].keys())
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header) for header in headers])

    workbook.save(Path(path))
