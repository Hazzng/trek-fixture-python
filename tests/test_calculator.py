"""Tests for the calculator module."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook

from trek_fixture.calculator import add, divide, export_xlsx, multiply, subtract


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


def test_export_xlsx_writes_real_workbook(tmp_path: Path) -> None:
    destination = tmp_path / "results.xlsx"
    results = [{"name": "alpha", "value": 1.5}, {"name": "beta", "value": 2}]

    export_xlsx(destination, results)

    workbook = load_workbook(destination)
    sheet = workbook.active
    assert sheet.title == "Results"
    assert [cell.value for cell in sheet[1]] == ["name", "value"]
    assert [cell.value for cell in sheet[2]] == ["alpha", 1.5]
    assert [cell.value for cell in sheet[3]] == ["beta", 2]
