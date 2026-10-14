"""Pure-logic tests for the audit building blocks: reading, validation, analysis and report rendering."""
import io
import zipfile
from decimal import Decimal

import pytest

from core.automation import analysis, report, tables, validation
from tests import audit_fixtures as fx

SRC = {"file_id": "file_x", "sha256": "ab" * 32, "sheet": "Transactions", "name": "audit.xlsx"}


def dataset(data=None, schema=None, name="audit.xlsx"):
    t = tables.read_table(data or fx.planted_xlsx(), name)
    return t, validation.validate_table(t, validation.parse_schema(schema or validation.AUDIT_SCHEMA))


# ------------------------------------------------------------------ reading
def test_reads_xlsx_with_headers_normalised_and_row_numbers_preserved():
    t = tables.read_table(fx.workbook(fx.clean_rows(3), blank_row_after=0), "a.xlsx")
    assert t.columns[:3] == ["txn_id", "date", "vendor"] and t.sheet == "Transactions" and t.header_row == 1
    assert [n for n, _ in t.rows] == [2, 4, 5] and t.blank_rows == 1       # the blank row 3 is skipped but numbering is the sheet's


def test_sheet_selection_and_unknown_sheet():
    data = fx.workbook(fx.clean_rows(2), extra_sheets=["Controls"])
    assert tables.read_table(data, "a.xlsx", "controls").sheet == "Controls"
    with pytest.raises(tables.TableError, match="not found"):
        tables.read_table(data, "a.xlsx", "Nope")


def test_reads_csv_including_semicolons():
    t = tables.read_table(fx.csv_bytes(fx.clean_rows(2)), "a.csv")
    assert len(t.rows) == 2 and t.columns[0] == "txn_id"
    semi = "txn_id;date;vendor;amount\nT1;2025-01-01;A;10\n".encode()
    assert tables.read_table(semi, "a.csv").columns == ["txn_id", "date", "vendor", "amount"]


@pytest.mark.parametrize("data,name,msg", [
    (b"not a zip", "a.xlsx", "not a valid .xlsx"),
    (b"\x00\x01binary", "a.csv", "binary"),
    (b"x", "a.xls", "Unsupported"),
    (b"x", "a.xlsm", "Unsupported"),
])
def test_malformed_files_are_rejected_with_a_reason(data, name, msg):
    with pytest.raises(tables.TableError, match=msg):
        tables.read_table(data, name)


def test_macro_workbooks_and_zip_bombs_are_refused():
    base = fx.clean_xlsx()
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base)) as src, zipfile.ZipFile(buf, "w") as dst:
        for i in src.infolist():
            dst.writestr(i, src.read(i))
        dst.writestr("xl/vbaProject.bin", b"macro")
    with pytest.raises(tables.TableError, match="macros"):
        tables.read_table(buf.getvalue(), "a.xlsx")
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", "<x/>")
        z.writestr("big.bin", b"\x00" * (101 * 1024 * 1024))
    with pytest.raises(tables.TableError, match="unreasonable"):
        tables.read_table(bomb.getvalue(), "a.xlsx")


def test_row_limit_is_an_error_not_a_silent_truncation(monkeypatch):
    monkeypatch.setattr(tables, "MAX_ROWS", 5)
    with pytest.raises(tables.TableError, match="more than"):
        tables.read_table(fx.workbook(fx.clean_rows(8)), "a.xlsx")


def test_empty_sheet_and_blank_header():
    with pytest.raises(tables.TableError, match="empty"):
        tables.read_table(fx.workbook([], headers=[]), "a.xlsx")
    with pytest.raises(tables.TableError, match="empty"):
        tables.read_table(fx.workbook([["a", None, "c"]], headers=["x", None, "z"]), "a.xlsx")


# ------------------------------------------------------------------ validation
def test_valid_rows_are_typed_and_bad_rows_quarantined_with_their_sheet_row():
    t, v = dataset()
    assert not v["blocking"]
    assert v["counts"]["rows_quarantined"] == 3 and v["counts"]["rows_valid"] == len(fx.planted_rows())
    nbad = len(fx.planted_rows()) + 2          # sheet rows: header + planted rows, then the three bad rows
    reasons = {q["row"]: sorted({e["code"] for e in q["errors"]}) for q in v["quarantined"]}
    assert reasons == {nbad: ["NOT_DATE"], nbad + 1: ["NOT_NUMBER"], nbad + 2: ["REQUIRED"]}
    assert all(isinstance(r["amount"], str) for r in v["rows"])          # money is carried as exact decimal strings
    first = v["rows"][0]
    assert first["_row"] == 2 and first["date"].startswith("2025-") and first["amount"] == "43"


def test_missing_required_columns_block_with_a_specific_message():
    data = fx.workbook(fx.clean_rows(3), headers=["Txn ID", "Date", "Vendor", "Dept", "Category", "Total", "Currency", "Approved By", "Receipt ID"])
    _, v = dataset(data)
    assert len(v["blocking"]) >= 1 and "amount" in v["blocking"][0] and v["rows"] == []


def test_duplicate_headers_and_no_data_block():
    _, v = dataset(fx.workbook(fx.clean_rows(2), headers=["Txn ID", "Date", "Vendor", "Department", "Category", "Amount", "Amount", "Approved By", "Receipt ID"]))
    assert any("Duplicate" in b for b in v["blocking"])
    _, v = dataset(fx.workbook([]))
    assert any("no data rows" in b for b in v["blocking"])


def test_duplicate_keys_and_uniqueness():
    rows = fx.clean_rows(3) + [["T-0001"] + fx.clean_rows(1)[0][1:]]
    _, v = dataset(fx.workbook(rows))
    assert [e["code"] for e in v["errors"]] == ["DUPLICATE_KEY"] and v["errors"][0]["row"] == 5


def test_error_ratio_guard_flags_a_wrong_shaped_file():
    rows = fx.bad_rows() * 3 + fx.clean_rows(2)
    _, v = dataset(fx.workbook(rows))
    assert any("invalid" in b for b in v["blocking"])


def test_future_dates_and_excel_error_cells_and_allowed_values():
    rows = [["T-1", "2999-01-01", "V", "Ops", "Travel", 10, "USD", "a", "r"], ["T-2", "2025-01-01", "V", "Ops", "Travel", "#REF!", "USD", "a", "r"],
            ["T-3", "2025-01-01", "V", "Ops", "Travel", 10, "XXX", "a", "r"], ["T-4", "2025-01-02", "V", "Ops", "Travel", 10, "USD", "a", "r"]] + fx.clean_rows(8)
    _, v = dataset(fx.workbook(rows))
    codes = {e["row"]: e["code"] for e in v["errors"]}
    assert codes[2] == "FUTURE_DATE" and codes[3] in ("CELL_ERROR", "NOT_NUMBER") and codes[4] == "NOT_ALLOWED" and 5 not in codes


def test_bad_schema_is_rejected_not_ignored():
    with pytest.raises(ValueError, match="columns"):
        validation.parse_schema({"columns": {"x": {"type": "no-such-type"}}})
    with pytest.raises(ValueError):
        validation.parse_schema({"unknown_key": 1})


# ------------------------------------------------------------------ analysis
def findings():
    _, v = dataset()
    out = analysis.analyze(v["rows"], analysis.AuditRules(), SRC)
    return out, v


def by_rule(out, rule):
    return [f for f in out["findings"] if f["rule_id"] == rule]


def test_every_planted_anomaly_is_found_and_traces_to_its_rows():
    out, v = findings()
    rowof = {r["txn_id"]: r["_row"] for r in v["rows"]}
    assert [f["txn_ids"] for f in by_rule(out, "AUD-001")] == [["T-0101"]]
    assert by_rule(out, "AUD-001")[0]["rows"] == [rowof["T-0101"]]
    assert {tuple(f["txn_ids"]) for f in by_rule(out, "AUD-002")} == {("T-0101",), ("T-0102",)}
    assert [f["txn_ids"] for f in by_rule(out, "AUD-003")] == [["T-0103", "T-0104"]]
    assert [f["txn_ids"] for f in by_rule(out, "AUD-004")] == [["T-0105", "T-0106"]]
    assert [f["txn_ids"] for f in by_rule(out, "AUD-006")] == [["T-0108"]]
    assert [f["txn_ids"] for f in by_rule(out, "AUD-007")] == [["T-0107"]]
    for f in out["findings"]:
        assert f["rows"] or f["rule_id"] == "AUD-005"
        assert all(r in rowof.values() for r in f["rows"]) and f["source"]["sha256"] == SRC["sha256"] and f["evidence"]


def test_clean_data_has_no_findings_and_ids_are_stable():
    _, v = dataset(fx.clean_xlsx())
    out = analysis.analyze(v["rows"], analysis.AuditRules(), SRC)
    assert out["findings"] == [] and out["summary"]["findings_count"] == 0
    a, _ = findings()
    b, _ = findings()
    assert [f["id"] for f in a["findings"]] == [f"F-{i:03d}" for i in range(1, len(a["findings"]) + 1)] and a == b   # deterministic


def test_money_is_exact_decimal_not_float():
    rows = [{"_row": i, "txn_id": f"T{i}", "date": "2025-01-01", "vendor": f"V{i}", "amount": "0.10", "currency": "USD"} for i in range(2, 12)]
    out = analysis.analyze(rows, analysis.AuditRules(expected_total=Decimal("1.00")), SRC)
    assert out["summary"]["total_amount"] == "1.00" and not by_rule(out, "AUD-005")          # 10 x 0.10 == 1.00 exactly (floats give 0.9999...)
    out = analysis.analyze(rows, analysis.AuditRules(expected_total=Decimal("1.01")), SRC)
    f = by_rule(out, "AUD-005")[0]
    assert f["evidence"]["difference"] == "-0.01" and f["amount_impact"] == "0.01"


def test_control_totals_and_multi_currency_guard():
    _, v = dataset()
    exact = sum((Decimal(r["amount"]) for r in v["rows"]), Decimal(0))
    ok = analysis.analyze(v["rows"], analysis.AuditRules(expected_total=exact, expected_count=len(v["rows"])), SRC)
    assert not by_rule(ok, "AUD-005")
    off = analysis.analyze(v["rows"], analysis.AuditRules(expected_total=exact + 5, expected_count=3), SRC)
    assert len(by_rule(off, "AUD-005")) == 2
    mixed = [dict(r) for r in v["rows"][:3]]
    mixed[0]["currency"] = "EUR"
    with pytest.raises(ValueError, match="several currencies"):
        analysis.analyze(mixed, analysis.AuditRules(expected_total=Decimal(1)), SRC)


def test_thresholds_are_configurable():
    _, v = dataset()
    default = analysis.analyze(v["rows"], analysis.AuditRules(), SRC)
    relaxed = analysis.analyze(v["rows"], analysis.AuditRules(approval_threshold=Decimal("1500")), SRC)
    assert len(by_rule(default, "AUD-004")) == 1 and by_rule(relaxed, "AUD-004") == []      # 600 + 700 no longer exceeds 1500
    assert len(by_rule(default, "AUD-001")) == len(by_rule(relaxed, "AUD-001")) == 1         # 2500 is above both


# ------------------------------------------------------------------ report
def render(narrative=None, cites=None, fs=None):
    out, v = findings()
    return report.render_html(title="Q1 <Audit>", prepared_for="Controller", run_id="run_1", generated_at="2025-01-01T00:00:00Z",
                              source=SRC, validation={**v["counts"], "quarantined": v["quarantined"]}, findings=fs if fs is not None else out["findings"],
                              summary=out["summary"], rules={"approval_threshold": "1000"}, narrative=narrative, narrative_cites=cites or []).decode()


def test_report_lists_every_finding_with_rows_and_escapes_everything():
    html = render()
    assert "T-0101" in html and "F-001" in html and "Rule AUD-003" in html and SRC["sha256"] in html
    assert "&lt;Audit&gt;" in html and "<Audit>" not in html
    assert "default-src 'none'" in html and "<script" not in html.lower()
    assert "NOT_DATE" not in html and "recognised date" in html     # data-quality section shows why rows were excluded


def test_hostile_cell_values_cannot_inject_html_or_formulas():
    evil = [{"id": "F-001", "rule_id": "AUD-001", "rule": "missing_approval", "severity": "high", "title": "<img src=x onerror=alert(1)>",
             "detail": "<script>alert(1)</script>", "rows": [2], "txn_ids": ["=cmd|' /C calc'!A0"], "amount_impact": "1.00", "evidence": {}, "source": SRC}]
    html = render(fs=evil)
    assert "<img" not in html and "<script>alert" not in html and "&lt;script&gt;" in html
    csv_text = report.findings_csv(evil).decode()
    assert "'=cmd" in csv_text and ",=cmd" not in csv_text


def test_ai_narrative_must_cite_real_findings_and_is_labelled():
    out, _ = findings()
    ids = [f["id"] for f in out["findings"]]
    assert report.validate_narrative("ok", [ids[0]], out["findings"]) is None
    assert "cite" in report.validate_narrative("text without sources", [], out["findings"])
    assert "do not exist" in report.validate_narrative("text", ["F-999"], out["findings"])
    assert "longer" in report.validate_narrative("x" * 5000, [ids[0]], out["findings"])
    html = render("Summary text", [ids[0]])
    assert "AI-generated, not independently verified" in html and ids[0] in html
