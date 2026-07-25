"""Tests for XLSX result export."""

from pathlib import Path
from typing import cast

import pytest
import tomllib
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from packaging.requirements import Requirement


def test_openpyxl_is_a_runtime_dependency() -> None:
    """The package metadata makes the exporter dependency available at runtime."""
    project_file = Path(__file__).parents[1] / "pyproject.toml"
    project = tomllib.loads(project_file.read_text())

    dependency_names = {
        Requirement(dependency).name.lower()
        for dependency in project["project"]["dependencies"]
    }
    assert "openpyxl" in dependency_names


def test_export_xlsx_round_trip(tmp_path: Path) -> None:
    """Exported results are preserved as rows in a valid workbook."""
    try:
        from trek_fixture.export import export_xlsx
    except ModuleNotFoundError as exc:
        pytest.fail(f"the XLSX exporter is unavailable: {exc}")

    output_path = tmp_path / "results.xlsx"
    results = [("2+2", 4), ("3*5", 15)]

    export_xlsx(output_path, results)

    assert output_path.is_file()
    workbook = load_workbook(output_path)
    try:
        worksheet = cast(Worksheet, workbook.active)
        assert list(worksheet.iter_rows(values_only=True)) == results
    finally:
        workbook.close()


def test_export_xlsx_preserves_all_blank_result_row(tmp_path: Path) -> None:
    """A result with two blank cells remains one blank row after loading."""
    from trek_fixture.export import export_xlsx

    output_path = tmp_path / "blank-result.xlsx"
    export_xlsx(output_path, [(None, None)])

    workbook = load_workbook(output_path)
    try:
        worksheet = cast(Worksheet, workbook.active)
        assert list(worksheet.iter_rows(values_only=True)) == [(None, None)]
    finally:
        workbook.close()
