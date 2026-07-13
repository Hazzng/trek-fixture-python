"""Export calculated expression results to Excel workbooks."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from math import isfinite
from os import PathLike
from typing import Any

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet


def _xlsx_value(value: Any) -> Any:
    """Return a value that Excel can persist without losing non-finite floats."""
    if isinstance(value, (float, Decimal)) and not isfinite(value):
        return str(value)
    return value


def export_xlsx(
    path: str | PathLike[str], results: Iterable[tuple[str, Any]]
) -> None:
    """Save expression/value pairs to an XLSX workbook at *path*.

    Each pair is written as one row with the expression in the first cell and
    its value in the second cell.  The worksheet contains no header row.
    """
    workbook = Workbook()
    worksheet = workbook.active
    if not isinstance(worksheet, Worksheet):
        raise RuntimeError("workbook has no active worksheet")
    for expression, value in results:
        worksheet.append([expression, _xlsx_value(value)])
        for cell in worksheet[worksheet.max_row]:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.data_type = "s"
    workbook.save(path)
    workbook.close()
