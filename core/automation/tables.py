"""Hardened Excel / CSV reading.

Limits protect the server (size, rows, columns, decompressed size). Macro workbooks (.xlsm) and legacy .xls are
refused. Formulas are read as their cached values only (`data_only`): nothing is ever evaluated, and a formula
that was never calculated by Excel reads as empty. Cells are never interpreted as code."""
import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Optional

MAX_ROWS = 20_000
MAX_COLS = 50
MAX_UNCOMPRESSED = 100 * 1024 * 1024
EXCEL_ERRORS = {"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A"}


class TableError(ValueError):
    """The file cannot be read as a table at all (a blocking problem, not a row-level one)."""


@dataclass
class Table:
    sheet: str
    sheets: list[str]
    columns: list[str]                 # normalized header names
    raw_headers: list[str]
    header_row: int                    # 1-based sheet row of the header
    rows: list[tuple[int, dict]] = field(default_factory=list)   # (sheet row number, {column: raw value})
    blank_rows: int = 0
    duplicate_headers: list[str] = field(default_factory=list)


def normalize(h: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(h if h is not None else "").strip().lower()).strip("_")


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def read_table(data: bytes, filename: str, sheet: Optional[str] = None) -> Table:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "xlsx":
        return _read_xlsx(data, sheet)
    if ext == "csv":
        return _read_csv(data)
    raise TableError(f"Unsupported file type '.{ext}'. Use .xlsx or .csv.")


def _build(sheet: str, sheets: list[str], grid, ) -> Table:
    header_row, headers, rows, blank = None, [], [], 0
    for n, values in grid:
        if header_row is None:
            if all(_empty(v) for v in values):
                continue
            header_row = n
            headers = list(values)
            while headers and _empty(headers[-1]):
                headers.pop()
            if len(headers) > MAX_COLS:
                raise TableError(f"The sheet has more than {MAX_COLS} columns.")
            continue
        vals = list(values[:len(headers)]) + [None] * max(0, len(headers) - len(values))
        if all(_empty(v) for v in vals):
            blank += 1
            continue
        if len(rows) >= MAX_ROWS:
            raise TableError(f"The sheet has more than {MAX_ROWS:,} data rows; split the file.")
        rows.append((n, vals))
    if header_row is None:
        raise TableError("The sheet is empty.")
    cols = [normalize(h) for h in headers]
    dup = sorted({c for c in cols if c and cols.count(c) > 1})
    empty_h = [i + 1 for i, c in enumerate(cols) if not c]
    if empty_h:
        raise TableError(f"Header cell(s) in column(s) {empty_h} are empty.")
    out = Table(sheet=sheet, sheets=sheets, columns=cols, raw_headers=[str(h).strip() for h in headers], header_row=header_row,
                blank_rows=blank, duplicate_headers=dup)
    out.rows = [(n, {c: v for c, v in zip(cols, vals)}) for n, vals in rows]
    return out


def _read_xlsx(data: bytes, sheet: Optional[str]) -> Table:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise TableError("The file is not a valid .xlsx workbook.")
    names = zf.namelist()
    if "xl/workbook.xml" not in names:
        raise TableError("The file is not a valid .xlsx workbook.")
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise TableError("Workbooks containing macros are not accepted.")
    if sum(i.file_size for i in zf.infolist()) > MAX_UNCOMPRESSED:
        raise TableError("The workbook expands to an unreasonable size.")
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise TableError(f"The workbook could not be read ({type(exc).__name__}).")
    try:
        sheets = list(wb.sheetnames)
        if not sheets:
            raise TableError("The workbook has no sheets.")
        if sheet:
            match = next((s for s in sheets if s.strip().lower() == sheet.strip().lower()), None)
            if match is None:
                raise TableError(f"Sheet '{sheet}' not found. Available sheets: {', '.join(sheets)}.")
        else:
            match = sheets[0]
        ws = wb[match]
        return _build(match, sheets, ((n, row) for n, row in enumerate(ws.iter_rows(values_only=True), start=1)))
    finally:
        wb.close()


def _read_csv(data: bytes) -> Table:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            raise TableError("The CSV file is not valid UTF-8 or Windows-1252 text.")
    if "\x00" in text:
        raise TableError("The CSV file contains binary data.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    return _build("csv", ["csv"], ((n, row) for n, row in enumerate(reader, start=1)))
