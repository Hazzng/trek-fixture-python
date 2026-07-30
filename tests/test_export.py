"""Tests for XLSX result export."""

from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import cast

import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet


def test_export_xlsx_round_trip(tmp_path: Path) -> None:
    """Exported results are preserved as ordered rows in a valid workbook."""
    try:
        export_xlsx = cast(
            Callable[..., None], import_module("trek_fixture.export").export_xlsx
        )
    except ModuleNotFoundError as exc:
        pytest.fail(f"the XLSX exporter is unavailable: {exc}")

    output_path = tmp_path / "results.xlsx"
    results = [("2+2", 4), ("3*5", 15)]

    export_xlsx(output_path, results)

    assert output_path.is_file()
    workbook = load_workbook(output_path)
    try:
        assert len(workbook.worksheets) == 1
        worksheet = cast(Worksheet, workbook.active)
        assert list(worksheet.iter_rows(values_only=True)) == results
    finally:
        workbook.close()
