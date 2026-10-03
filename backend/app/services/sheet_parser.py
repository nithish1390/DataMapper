"""
Reads an uploaded mapping-sheet file (CSV, modern .xlsx, or legacy .xls)
into raw string rows.

Trusting the file extension alone caused a crash: a file named ".xlsx" that
is actually a legacy binary .xls (or just not a valid zip for any other
reason — a browser/OS sometimes mis-names or mis-types an upload) made
openpyxl explode with a raw KeyError instead of a clear error, because
openpyxl only understands the modern zip-based xlsx format. This module
instead sniffs the real file signature and routes to the right parser, or
raises SheetFormatError with an actionable message.
"""
from __future__ import annotations

import csv
import io
import zipfile

from openpyxl import load_workbook

try:
    import xlrd  # legacy .xls (OLE binary format) support
except ImportError:  # pragma: no cover - optional dependency
    xlrd = None  # type: ignore[assignment]

XLSX_MAGIC = b"PK\x03\x04"  # zip local file header signature
XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # OLE compound file signature


class SheetFormatError(ValueError):
    """Raised when the uploaded file can't be read as CSV, .xlsx, or .xls."""


def sniff_kind(data: bytes, filename: str) -> str:
    """Returns 'xlsx', 'xls', or 'csv', based on the actual file bytes
    first and the filename only as a fallback hint."""
    if data.startswith(XLSX_MAGIC):
        if _is_numbers_package(data):
            # Apple Numbers documents are also zips, but contain Index/*.iwa
            # instead of [Content_Types].xml — openpyxl can't read them.
            raise SheetFormatError(
                f'"{filename}" is an Apple Numbers document, not an Excel file '
                "(it was probably renamed to .xlsx). Open it in Numbers and use "
                "File → Export To → Excel… (or CSV…), then upload the exported file."
            )
        return "xlsx"
    if data.startswith(XLS_MAGIC):
        return "xls"
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        # Named .xlsx but doesn't have a zip signature — almost always a
        # mis-saved/renamed file. Fail clearly rather than let openpyxl crash.
        raise SheetFormatError(
            f'"{filename}" is named .xlsx but is not a valid Excel (zip) file. '
            "It may be an old .xls file renamed, or corrupted — try re-saving it "
            "as .xlsx or .csv from Excel."
        )
    if name.endswith(".xls"):
        raise SheetFormatError(
            f'"{filename}" is named .xls but its content doesn\'t match the legacy '
            "Excel format either. Try re-saving it as .xlsx or .csv from Excel."
        )
    return "csv"


def _is_numbers_package(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" not in names and "Index/Document.iwa" in names


def parse_csv_bytes(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return [row for row in reader if any(cell.strip() for cell in row)]


def list_xlsx_sheets(data: bytes) -> list[str]:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise SheetFormatError(f"Could not open as .xlsx: {exc}") from exc
    try:
        return wb.sheetnames
    finally:
        wb.close()


def parse_xlsx_sheet(data: bytes, sheet_name: str) -> list[list[str]]:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise SheetFormatError(f"Could not open as .xlsx: {exc}") from exc
    try:
        ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
        rows: list[list[str]] = []
        for row in ws.iter_rows(values_only=True):
            if any(c is not None and str(c).strip() for c in row):
                rows.append(["" if c is None else str(c) for c in row])
        return rows
    finally:
        wb.close()


def list_xls_sheets(data: bytes) -> list[str]:
    if xlrd is None:
        raise SheetFormatError(
            "This looks like a legacy .xls file, but the backend's xlrd dependency "
            "isn't installed. Run `pip install -r requirements.txt` again, or re-save "
            "the file as .xlsx or .csv from Excel."
        )
    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception as exc:  # noqa: BLE001
        raise SheetFormatError(f"Could not open as legacy .xls: {exc}") from exc
    return book.sheet_names()


def parse_xls_sheet(data: bytes, sheet_name: str) -> list[list[str]]:
    if xlrd is None:
        raise SheetFormatError(
            "This looks like a legacy .xls file, but the backend's xlrd dependency "
            "isn't installed. Run `pip install -r requirements.txt` again, or re-save "
            "the file as .xlsx or .csv from Excel."
        )
    try:
        book = xlrd.open_workbook(file_contents=data)
        sheet = book.sheet_by_name(sheet_name) if sheet_name in book.sheet_names() else book.sheet_by_index(0)
    except Exception as exc:  # noqa: BLE001
        raise SheetFormatError(f"Could not open as legacy .xls: {exc}") from exc
    rows: list[list[str]] = []
    for r in range(sheet.nrows):
        row = ["" if c is None else str(c) for c in sheet.row_values(r)]
        if any(cell.strip() for cell in row):
            rows.append(row)
    return rows
