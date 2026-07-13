"""Tests for the calculator module."""

import pytest

from pint import DimensionalityError, Quantity

from trek_fixture.calculator import add, convert, divide, multiply, subtract, ureg


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


def test_convert_meters_to_feet() -> None:
    assert convert(1, "meter", "foot") == pytest.approx(3.28084, rel=1e-5)


def test_convert_kilograms_to_pounds() -> None:
    assert convert(1, "kilogram", "pound") == pytest.approx(2.20462, rel=1e-5)


def test_add_compatible_quantities() -> None:
    result = add(1 * ureg.meter, 1 * ureg.foot)

    assert isinstance(result, Quantity)
    assert result.to("meter").magnitude == pytest.approx(1.3048, rel=1e-5)
    assert result.units == ureg.meter


def test_add_remains_compatible_with_scalars() -> None:
    assert add(2, 3) == 5


def test_add_rejects_incompatible_dimensions() -> None:
    with pytest.raises(DimensionalityError):
        add(1 * ureg.meter, 1 * ureg.second)
