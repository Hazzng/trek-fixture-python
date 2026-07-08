"""Tests for the calculator module."""

import pytest

from trek_fixture.calculator import add, divide, multiply, subtract  # type: ignore[import-untyped]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (2, 3, 5),
        (-1, 1, 0),
        (0, 0, 0),
        (1.5, 2.25, 3.75),
    ],
)
def test_add(a: float, b: float, expected: float) -> None:
    assert add(a, b) == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (5, 3, 2),
        (3, 5, -2),
        (0, 4, -4),
    ],
)
def test_subtract(a: float, b: float, expected: float) -> None:
    assert subtract(a, b) == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (4, 3, 12),
        (-2, 3, -6),
        (1.5, 2, 3.0),
    ],
)
def test_multiply(a: float, b: float, expected: float) -> None:
    assert multiply(a, b) == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (10, 2, 5),
        (9, 3, 3),
        (7.5, 2.5, 3.0),
    ],
)
def test_divide(a: float, b: float, expected: float) -> None:
    assert divide(a, b) == expected


def test_divide_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)
