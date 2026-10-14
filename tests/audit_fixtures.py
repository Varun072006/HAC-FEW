"""Disposable audit-file fixtures, generated in memory. Dates are fixed in the past so the suite never ages out.

PLANTED, with the rule that must find each (row numbers are sheet rows; row 1 is the header):
  AUD-001 missing approval   T-0101 (2500, no approver)
  AUD-002 missing receipt    T-0102 (300, no receipt)           [T-0101 also lacks a receipt]
  AUD-003 duplicate          T-0103 + T-0104 (Acme Supplies, 480.00, one day apart)
  AUD-004 split payment      T-0105 + T-0106 (Globex, 600 + 700 the same day)
  AUD-006 outlier            T-0108 (Meals, 900 among ~40s)
  AUD-007 negative amount    T-0107 (-150)
  quarantined (data errors)  bad date, non-numeric amount, missing id
"""
import io
from decimal import Decimal

from openpyxl import Workbook

HEADERS = ["Txn ID", "Date", "Vendor", "Department", "Category", "Amount", "Currency", "Approved By", "Receipt ID"]


def clean_rows(n=20):
    return [[f"T-{i:04d}", f"2025-02-{(i % 27) + 1:02d}", f"Vendor {i % 6}", "Ops", "Travel", 40 + (i * 3) % 80, "USD", "j.smith", f"R-{i}"]
            for i in range(1, n + 1)]


def planted_rows():
    r = clean_rows(20)
    r += [
        ["T-0101", "2025-03-04", "Initech", "Ops", "Equipment", 2500, "USD", None, None],
        ["T-0102", "2025-03-05", "Staples", "Admin", "Supplies", 300, "USD", "j.smith", None],
        ["T-0103", "2025-03-02", "Acme Supplies", "Admin", "Supplies", 480, "USD", "j.smith", "R-901"],
        ["T-0104", "2025-03-03", "Acme Supplies", "Admin", "Supplies", 480, "USD", "j.smith", "R-902"],
        ["T-0105", "2025-03-10", "Globex", "Ops", "Services", 600, "USD", "j.smith", "R-903"],
        ["T-0106", "2025-03-10", "Globex", "Ops", "Services", 700, "USD", "j.smith", "R-904"],
        ["T-0107", "2025-03-11", "Hooli", "Ops", "Refunds", -150, "USD", "j.smith", "R-905"],
    ]
    r += [[f"T-02{i:02d}", f"2025-03-{12 + i:02d}", f"Cafe {i}", "Sales", "Meals", 30 + i * 2, "USD", "j.smith", f"R-3{i}"] for i in range(10)]
    r += [["T-0108", "2025-03-25", "Chez Luxe", "Sales", "Meals", 900, "USD", "j.smith", "R-906"]]
    return r


def bad_rows():
    return [["T-0300", "not-a-date", "Initech", "Ops", "Travel", 50, "USD", "j.smith", "R-1"],
            ["T-0301", "2025-03-01", "Initech", "Ops", "Travel", "abc", "USD", "j.smith", "R-2"],
            [None, "2025-03-01", "Initech", "Ops", "Travel", 50, "USD", "j.smith", "R-3"]]


def workbook(rows, headers=HEADERS, sheet="Transactions", extra_sheets=(), blank_row_after=None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for i, row in enumerate(rows):
        ws.append(row)
        if blank_row_after == i:
            ws.append([])
    for name in extra_sheets:
        wb.create_sheet(name).append(["x"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def planted_xlsx(**kw) -> bytes:
    return workbook(planted_rows() + bad_rows(), **kw)


def clean_xlsx() -> bytes:
    return workbook(clean_rows(25))


def csv_bytes(rows, headers=HEADERS) -> bytes:
    import csv
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(headers)
    w.writerows(["" if c is None else c for c in r] for r in rows)
    return out.getvalue().encode()


def total(rows) -> Decimal:
    return sum((Decimal(str(r[5])) for r in rows if isinstance(r[5], (int, float))), Decimal(0))
