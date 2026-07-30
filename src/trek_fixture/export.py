"""Export calculation results to an Excel workbook."""

from __future__ import annotations

from collections.abc import Iterable
from os import PathLike
from typing import Any, cast

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet


def export_xlsx(
    path: str | PathLike[str], results: Iterable[tuple[Any, Any]]
) -> None:
    """Save calculation expression/value pairs as ordered worksheet rows.

    Each pair in ``results`` becomes one row, with the expression in the first
    cell and its calculated value in the second cell.
    """
    workbook = Workbook()
    worksheet = cast(Worksheet, workbook.active)
    for expression, value in results:
        worksheet.append((expression, value))
    workbook.save(path)
