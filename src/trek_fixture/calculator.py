"""A minimal, well-tested calculator module.

Deterministic and dependency-free so the spike's sandbox can clone and run
its tests reproducibly.
"""

from __future__ import annotations


def add(a: float, b: float) -> float:
    """Return the sum of two numbers."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return the difference of two numbers."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of two numbers."""
    return a * b


def power(base: float, exponent: float) -> float:
    """Raise ``base`` to ``exponent`` using Python exponentiation semantics."""
    return base**exponent


def divide(a: float, b: float) -> float:
    """Return the quotient of two numbers.

    Raises:
        ZeroDivisionError: if ``b`` is zero.
    """
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a / b
