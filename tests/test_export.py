"""Tests for the XLSX exporter."""

from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook

from trek_fixture.export import export_xlsx


def test_export_xlsx_writes_expression_value_rows(tmp_path: Path) -> None:
    """Exported rows preserve each expression/value pair without a header."""
    destination = tmp_path / "results.xlsx"
    results = [("2 + 2", 4), ("greeting", "hello")]

    export_xlsx(destination, results)

    workbook = load_workbook(destination, read_only=True)
    try:
        worksheet = workbook.active
        assert worksheet is not None
        assert list(worksheet.iter_rows(values_only=True)) == [
            ("2 + 2", 4),
            ("greeting", "hello"),
        ]
    finally:
        workbook.close()


def test_export_xlsx_creates_valid_ooxml_workbook(tmp_path: Path) -> None:
    """The output is a readable OOXML ZIP workbook, not a text placeholder."""
    destination = tmp_path / "results.xlsx"

    export_xlsx(destination, [("answer", 42)])

    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert "[Content_Types].xml" in names
        assert "xl/workbook.xml" in names
        assert "xl/worksheets/sheet1.xml" in names
