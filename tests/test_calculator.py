from trek_fixture.calculator import power


def test_power_positive_exponent() -> None:
    assert power(2, 3) == 8


def test_power_zero_exponent() -> None:
    assert power(5, 0) == 1


def test_power_negative_exponent() -> None:
    assert power(2, -1) == 0.5
