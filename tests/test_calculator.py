"""Tests for the calculator module."""

import inspect
from pathlib import Path
import tomllib

import pytest

from trek_fixture import calculator
from trek_fixture.calculator import add, divide, multiply, subtract


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


def test_power_supports_numeric_exponents_and_has_a_typed_return() -> None:
    assert calculator.power(2, 10) == 1024
    assert calculator.power(3, 2) == 9
    assert inspect.signature(calculator.power).return_annotation in (float, "float")


def test_runtime_dependencies_include_redis_and_postgresql_client() -> None:
    project_file = Path(__file__).parents[1] / "pyproject.toml"
    with project_file.open("rb") as file:
        project = tomllib.load(file)

    dependencies = project["project"]["dependencies"]
    assert any(dependency.split("[", 1)[0].split("=", 1)[0] == "redis" for dependency in dependencies)
    assert any(
        dependency.split("[", 1)[0].split("=", 1)[0] in {"psycopg", "psycopg2", "psycopg2-binary"}
        for dependency in dependencies
    )
