"""Tests for XLSX result export."""

from pathlib import Path
import tomllib

import pytest
from openpyxl import load_workbook


def test_openpyxl_is_a_runtime_dependency() -> None:
    """The package metadata makes the exporter dependency available at runtime."""
    project_file = Path(__file__).parents[1] / "pyproject.toml"
    project = tomllib.loads(project_file.read_text())

    assert "openpyxl" in project["project"]["dependencies"]


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
        assert len(workbook.worksheets) == 1
        worksheet = workbook.active
        assert list(worksheet.iter_rows(values_only=True)) == results
    finally:
        workbook.close()
