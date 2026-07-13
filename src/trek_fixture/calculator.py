"""A minimal, well-tested calculator module.

Deterministic and dependency-free so the spike's sandbox can clone and run
its tests reproducibly.
"""

from __future__ import annotations

from os import PathLike
from typing import Any, Iterable

from openpyxl import Workbook


def export_xlsx(
    path: str | PathLike[str], results: Iterable[tuple[Any, ...]]
) -> None:
    """Write calculation-result tuples to an OOXML workbook.

    Each tuple is written as one worksheet row, preserving the input order.
    """
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    for result in results:
        worksheet.append(result)
    workbook.save(path)


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
