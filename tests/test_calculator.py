"""Tests for the calculator module."""

import pytest

from trek_fixture.calculator import add, divide, multiply, power, subtract


def test_add() -> None:
    assert add(2, 3) == 5
    assert add(-1, 1) == 0


def test_subtract() -> None:
    assert subtract(5, 3) == 2


def test_multiply() -> None:
    assert multiply(4, 3) == 12


def test_divide() -> None:
    assert divide(10, 2) == 5


def test_divide_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)


def test_power_positive_exponent() -> None:
    assert power(2, 3) == 8


def test_power_zero_exponent() -> None:
    assert power(5, 0) == 1


def test_power_negative_exponent() -> None:
    assert power(2, -1) == 0.5
