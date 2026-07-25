"""Export calculation results to Excel workbooks."""

from __future__ import annotations

from collections.abc import Iterable
from os import PathLike
from typing import Any, cast

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

Result = tuple[Any, Any]


def export_xlsx(path: str | PathLike[str], results: Iterable[Result]) -> None:
    """Save calculation ``results`` as rows in an XLSX workbook.

    Each result tuple is appended as one worksheet row, preserving the tuple's
    expression and value cells in their original order.
    """
    workbook = Workbook()
    worksheet = cast(Worksheet, workbook.active)
    for result in results:
        worksheet.append(list(result))
    workbook.save(path)
