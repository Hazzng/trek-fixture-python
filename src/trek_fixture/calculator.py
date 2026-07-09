"""A minimal, well-tested calculator module.

Deterministic and dependency-free so the spike's sandbox can clone and run
its tests reproducibly.
"""

from __future__ import annotations

from pint import UnitRegistry

_ureg: UnitRegistry = UnitRegistry()


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


def convert_length(value: float, source_unit: str, target_unit: str) -> float:
    """Convert a length value between compatible units using Pint."""
    return (_ureg.Quantity(value, source_unit).to(target_unit)).magnitude
