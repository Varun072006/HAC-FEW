"""Schema validation for tabular data. Produces a typed, normalized dataset plus precise, row-level errors.

Blocking problems (missing required columns, duplicate headers, too many invalid rows) stop the workflow. Row-level
problems quarantine just that row, so one bad cell never silently corrupts a total or disappears: every
quarantined row is listed with its sheet row number and reason, and the report shows them."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.automation.tables import EXCEL_ERRORS, Table, normalize

MAX_ERROR_DETAILS = 500


class ColumnRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["string", "integer", "decimal", "date"] = "string"
    required: bool = False
    unique: bool = False
    allowed: Optional[list[str]] = None
    min: Optional[Decimal] = None
    max: Optional[Decimal] = None
    max_length: Optional[int] = Field(default=None, ge=1, le=10_000)
    not_future: bool = False


class TableSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required_columns: list[str] = Field(default_factory=list, max_length=50)
    columns: dict[str, ColumnRule] = Field(default_factory=dict)
    max_invalid_ratio: float = Field(default=0.5, ge=0, le=1)

    @field_validator("required_columns")
    @classmethod
    def _norm_required(cls, v):
        return [normalize(x) for x in v]

    @field_validator("columns")
    @classmethod
    def _norm_columns(cls, v):
        return {normalize(k): r for k, r in v.items()}


def parse_schema(raw: Any) -> TableSchema:
    try:
        return TableSchema.model_validate(raw or {})
    except ValidationError as exc:
        raise ValueError("; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]))


AUDIT_SCHEMA = {
    "required_columns": ["txn_id", "date", "vendor", "amount"],
    "columns": {
        "txn_id": {"type": "string", "required": True, "unique": True, "max_length": 40},
        "date": {"type": "date", "required": True, "not_future": True},
        "vendor": {"type": "string", "required": True, "max_length": 120},
        "department": {"type": "string", "max_length": 80},
        "category": {"type": "string", "max_length": 80},
        "amount": {"type": "decimal", "required": True, "min": "-10000000", "max": "10000000"},
        "currency": {"type": "string", "allowed": ["USD", "EUR", "GBP", "INR"]},
        "approved_by": {"type": "string", "max_length": 80},
        "receipt_id": {"type": "string", "max_length": 60},
    },
    "max_invalid_ratio": 0.5,
}


def _cell(v: Any, rule: ColumnRule):
    """Returns (normalized value or None, error_code or None, message)."""
    if isinstance(v, str):
        v = v.strip()
    if v is None or v == "":
        return None, None, ""
    if isinstance(v, str) and v.upper() in EXCEL_ERRORS:
        return None, "CELL_ERROR", f"Cell holds the spreadsheet error {v}."
    if rule.type == "string":
        s = str(v).strip()
        if rule.max_length and len(s) > rule.max_length:
            return None, "TOO_LONG", f"Longer than {rule.max_length} characters."
        if rule.allowed is not None and s not in rule.allowed:
            return None, "NOT_ALLOWED", f"'{s}' is not one of: {', '.join(rule.allowed)}."
        return s, None, ""
    if rule.type == "integer":
        try:
            d = Decimal(str(v))
            if d != d.to_integral_value():
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            return None, "NOT_INTEGER", f"'{v}' is not a whole number."
        n = int(d)
        if (rule.min is not None and Decimal(n) < rule.min) or (rule.max is not None and Decimal(n) > rule.max):
            return None, "OUT_OF_RANGE", f"{n} is outside the allowed range."
        return n, None, ""
    if rule.type == "decimal":
        if isinstance(v, bool):
            return None, "NOT_NUMBER", "A yes/no value is not a number."
        try:
            raw = str(v).replace(",", "") if isinstance(v, str) else repr(v) if isinstance(v, float) else str(v)
            d = Decimal(raw)
            if not d.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            return None, "NOT_NUMBER", f"'{v}' is not a number."
        if (rule.min is not None and d < rule.min) or (rule.max is not None and d > rule.max):
            return None, "OUT_OF_RANGE", f"{d} is outside the allowed range."
        return format(d, "f"), None, ""
    # date
    d: Optional[date] = None
    if isinstance(v, datetime):
        d = v.date()
    elif isinstance(v, date):
        d = v
    else:
        s = str(v).strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                d = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                continue
    if d is None:
        return None, "NOT_DATE", f"'{v}' is not a recognised date."
    if rule.not_future and d > date.today():
        return None, "FUTURE_DATE", f"{d.isoformat()} is in the future."
    return d.isoformat(), None, ""


def validate_table(table: Table, schema: TableSchema) -> dict:
    """Returns {blocking, errors, error_total, rows, quarantined, columns, counts}. Never raises for data problems."""
    blocking: list[str] = []
    missing = [c for c in schema.required_columns if c not in table.columns]
    if missing:
        blocking.append(f"Missing required column(s): {', '.join(missing)}. Found: {', '.join(table.raw_headers) or 'none'}.")
    if table.duplicate_headers:
        blocking.append(f"Duplicate column header(s): {', '.join(table.duplicate_headers)}.")
    for c in schema.columns:
        if schema.columns[c].required and c not in table.columns and c not in missing:
            blocking.append(f"Missing required column: {c}.")
    if not table.rows:
        blocking.append("The sheet has a header but no data rows.")
    rules = {c: r for c, r in schema.columns.items() if c in table.columns}

    errors: list[dict] = []
    error_total = 0
    good: list[dict] = []
    quarantined: list[dict] = []
    seen_unique: dict[str, dict[str, int]] = {c: {} for c, r in rules.items() if r.unique}
    if not blocking:
        for rown, raw in table.rows:
            row_errors: list[dict] = []
            norm: dict[str, Any] = {}
            for col in table.columns:
                rule = rules.get(col)
                if rule is None:
                    v = raw.get(col)
                    norm[col] = None if v is None or (isinstance(v, str) and not v.strip()) else (v.isoformat() if isinstance(v, (date, datetime)) else str(v).strip() if isinstance(v, str) else v)
                    if isinstance(norm[col], str) and norm[col].upper() in EXCEL_ERRORS:
                        row_errors.append({"row": rown, "column": col, "code": "CELL_ERROR", "message": f"Cell holds the spreadsheet error {norm[col]}."})
                    continue
                val, code, msg = _cell(raw.get(col), rule)
                if code:
                    row_errors.append({"row": rown, "column": col, "code": code, "message": msg})
                elif val is None and rule.required:
                    row_errors.append({"row": rown, "column": col, "code": "REQUIRED", "message": "A value is required."})
                norm[col] = val
            for col, seen in seen_unique.items():
                v = norm.get(col)
                if v is not None:
                    if v in seen:
                        row_errors.append({"row": rown, "column": col, "code": "DUPLICATE_KEY", "message": f"'{v}' already appears on row {seen[v]}."})
                    else:
                        seen[v] = rown
            if row_errors:
                error_total += len(row_errors)
                errors.extend(row_errors[: max(0, MAX_ERROR_DETAILS - len(errors))])
                quarantined.append({"row": rown, "errors": row_errors[:10]})
            else:
                good.append({"_row": rown, **norm})
        total = len(table.rows)
        if total and len(quarantined) / total > schema.max_invalid_ratio:
            blocking.append(f"{len(quarantined)} of {total} rows are invalid (more than the {int(schema.max_invalid_ratio * 100)}% allowed); the file is probably the wrong shape.")
    return {"blocking": blocking, "errors": errors, "error_total": error_total, "rows": good, "quarantined": quarantined,
            "columns": table.columns,
            "counts": {"rows_read": len(table.rows), "rows_valid": len(good), "rows_quarantined": len(quarantined), "blank_rows": table.blank_rows}}
