"""A minimal calculator with optional Pint quantity support."""

from __future__ import annotations

from pint import Quantity, UnitRegistry


ureg: UnitRegistry = UnitRegistry()
"""The unit registry owned by this calculator module."""


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a numeric value between units and return its magnitude."""
    quantity = ureg.Quantity(value, from_unit)
    return quantity.to(to_unit).magnitude


def add(a: float | Quantity, b: float | Quantity) -> float | Quantity:
    """Return the sum of two numbers or compatible Pint quantities."""
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
