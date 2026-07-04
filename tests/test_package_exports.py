"""Tests for the trek_fixture package exports."""

from trek_fixture import __version__, add, divide, multiply, power, slugify, subtract


def test_package_re_exports_public_helpers() -> None:
    assert __version__ == "0.1.0"
    assert add(1, 2) == 3
    assert subtract(5, 3) == 2
    assert multiply(2, 4) == 8
    assert divide(8, 2) == 4
    assert power(2, 3) == 8
    assert slugify("Hello World") == "hello-world"
