from __future__ import annotations

import pytest

from trek_fixture import calculator


def test_convert_length_uses_pint_units() -> None:
    assert calculator.convert_length(1, "meter", "centimeter") == pytest.approx(100)


def test_convert_length_rejects_unknown_units() -> None:
    with pytest.raises(Exception):
        calculator.convert_length(1, "made_up_unit", "meter")
