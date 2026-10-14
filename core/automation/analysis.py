"""Audit analysis: deterministic rules over a validated dataset. Money uses Decimal, never float, so totals are exact
and reproducible. Every finding carries the sheet rows it came from, the values that triggered it, and the source file's
hash, so it can be traced back to the evidence. Thresholds apply to the stated amount; there is no currency conversion."""
import statistics
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

RULESET_VERSION = "audit-rules-1.0"
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
RULES = {
    "AUD-001": ("missing_approval", "high", "Amount above the approval threshold has no approver"),
    "AUD-002": ("missing_receipt", "medium", "Amount above the receipt threshold has no receipt reference"),
    "AUD-003": ("duplicate_transaction", "high", "Same vendor and amount posted more than once within the duplicate window"),
    "AUD-004": ("split_transaction", "high", "Same-day payments to one vendor that each stay under the approval threshold but exceed it together"),
    "AUD-005": ("control_total_mismatch", "high", "Dataset total or row count differs from the declared control figure"),
    "AUD-006": ("amount_outlier", "medium", "Amount is a statistical outlier within its category"),
    "AUD-007": ("negative_amount", "low", "Negative amount (credit or reversal) needs supporting documentation"),
}


class AuditRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_threshold: Decimal = Field(default=Decimal("1000"), ge=0)
    receipt_threshold: Decimal = Field(default=Decimal("75"), ge=0)
    duplicate_window_days: int = Field(default=3, ge=0, le=60)
    outlier_z: float = Field(default=3.0, gt=0, le=10)
    outlier_min_group: int = Field(default=8, ge=3, le=1000)
    expected_total: Optional[Decimal] = None
    expected_count: Optional[int] = Field(default=None, ge=0)


def _d(v: Any) -> Decimal:
    return Decimal(str(v))


def _money(d: Decimal) -> str:
    return format(d.quantize(Decimal("0.01")), "f")


def analyze(rows: list[dict], rules: AuditRules, source: dict) -> dict:
    """rows: dataset rows ({_row, txn_id, date, vendor, amount, ...}). Returns {findings, summary}."""
    findings: list[dict] = []
    by_row = {r["_row"]: r for r in rows}
    currencies = sorted({r.get("currency") for r in rows if r.get("currency")})

    def add(rule_id: str, rown: list[int], title: str, detail: str, impact: Decimal, evidence: dict) -> None:
        name, severity, _ = RULES[rule_id]
        findings.append({"rule_id": rule_id, "rule": name, "severity": severity, "title": title, "detail": detail,
                         "rows": sorted(rown), "txn_ids": [by_row[x].get("txn_id") for x in sorted(rown)],
                         "amount_impact": _money(impact), "evidence": evidence, "source": source})

    for r in rows:
        amt = _d(r["amount"])
        if amt < 0:
            add("AUD-007", [r["_row"]], f"Negative amount on {r.get('txn_id')}", f"{_money(amt)} {r.get('currency') or ''}".strip() + " posted to " + str(r.get("vendor")),
                abs(amt), {"amount": r["amount"], "vendor": r.get("vendor")})
        if amt > rules.approval_threshold and not r.get("approved_by"):
            add("AUD-001", [r["_row"]], f"No approver recorded for {r.get('txn_id')}",
                f"{_money(amt)} exceeds the approval threshold of {_money(rules.approval_threshold)} and the approved_by field is empty.",
                amt, {"amount": r["amount"], "threshold": _money(rules.approval_threshold), "vendor": r.get("vendor")})
        if amt > rules.receipt_threshold and not r.get("receipt_id"):
            add("AUD-002", [r["_row"]], f"No receipt reference for {r.get('txn_id')}",
                f"{_money(amt)} exceeds the receipt threshold of {_money(rules.receipt_threshold)} and receipt_id is empty.",
                amt, {"amount": r["amount"], "threshold": _money(rules.receipt_threshold), "vendor": r.get("vendor")})

    # duplicates: same vendor + same amount within the window (grouped, so a triple is one finding)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(str(r.get("vendor", "")).lower(), r["amount"], r.get("currency"))].append(r)
    for (vendor, amount, _cur), grp in sorted(groups.items(), key=lambda kv: min(x["_row"] for x in kv[1])):
        if len(grp) < 2:
            continue
        grp = sorted(grp, key=lambda x: (x["date"], x["_row"]))
        cluster = [grp[0]]
        clusters = []
        for x in grp[1:]:
            if (date.fromisoformat(x["date"]) - date.fromisoformat(cluster[-1]["date"])).days <= rules.duplicate_window_days:
                cluster.append(x)
            else:
                clusters.append(cluster)
                cluster = [x]
        clusters.append(cluster)
        for c in clusters:
            if len(c) >= 2:
                add("AUD-003", [x["_row"] for x in c], f"{len(c)} postings of {amount} to {c[0].get('vendor')}",
                    f"Transactions {', '.join(str(x.get('txn_id')) for x in c)} have the same vendor and amount within {rules.duplicate_window_days} day(s).",
                    _d(amount) * (len(c) - 1), {"amount": amount, "vendor": c[0].get("vendor"), "dates": [x["date"] for x in c]})

    # split transactions: same vendor, same day, each <= threshold, together > threshold
    by_day: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if _d(r["amount"]) > 0:
            by_day[(str(r.get("vendor", "")).lower(), r["date"], r.get("currency"))].append(r)
    for (vendor, day, _cur), grp in sorted(by_day.items(), key=lambda kv: min(x["_row"] for x in kv[1])):
        total = sum((_d(x["amount"]) for x in grp), Decimal(0))
        if len(grp) >= 2 and all(_d(x["amount"]) <= rules.approval_threshold for x in grp) and total > rules.approval_threshold:
            add("AUD-004", [x["_row"] for x in grp], f"Possible split payment to {grp[0].get('vendor')} on {day}",
                f"{len(grp)} payments of {', '.join(x['amount'] for x in grp)} total {_money(total)}, above the {_money(rules.approval_threshold)} approval threshold.",
                total, {"vendor": grp[0].get("vendor"), "date": day, "amounts": [x["amount"] for x in grp], "total": _money(total)})

    # outliers within category (population stdev; needs a reasonable group)
    cats: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("category") and _d(r["amount"]) > 0:
            cats[r["category"]].append(r)
    for cat in sorted(cats):
        grp = cats[cat]
        if len(grp) < rules.outlier_min_group:
            continue
        vals = [float(_d(x["amount"])) for x in grp]
        mean, sd = statistics.fmean(vals), statistics.pstdev(vals)
        if sd == 0:
            continue
        for x in grp:
            z = (float(_d(x["amount"])) - mean) / sd
            if z >= rules.outlier_z:
                add("AUD-006", [x["_row"]], f"{x.get('txn_id')} is unusually large for {cat}",
                    f"{x['amount']} is {z:.1f} standard deviations above the {cat} mean of {mean:.2f} (n={len(grp)}).",
                    _d(x["amount"]) - Decimal(str(round(mean, 2))), {"category": cat, "amount": x["amount"], "mean": round(mean, 2), "z": round(z, 2), "n": len(grp)})

    # control totals (exact)
    total_amount = sum((_d(r["amount"]) for r in rows), Decimal(0))
    control_note = None
    if rules.expected_total is not None or rules.expected_count is not None:
        if len(currencies) > 1 and rules.expected_total is not None:
            raise ValueError(f"A control total cannot be reconciled across several currencies ({', '.join(currencies)}); filter the data to one currency.")
        if rules.expected_total is not None and total_amount != rules.expected_total:
            diff = total_amount - rules.expected_total
            add("AUD-005", [], "Dataset total differs from the control total",
                f"Computed total {_money(total_amount)} vs declared {_money(rules.expected_total)} (difference {_money(diff)}).", abs(diff),
                {"computed_total": _money(total_amount), "expected_total": _money(rules.expected_total), "difference": _money(diff)})
        if rules.expected_count is not None and len(rows) != rules.expected_count:
            add("AUD-005", [], "Row count differs from the control count",
                f"{len(rows)} valid rows vs {rules.expected_count} declared.", Decimal(0),
                {"computed_count": len(rows), "expected_count": rules.expected_count})
        control_note = "checked"

    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["rule_id"], f["rows"][0] if f["rows"] else 0))
    for i, f in enumerate(findings, 1):
        f["id"] = f"F-{i:03d}"
    exposure = sum((_d(f["amount_impact"]) for f in findings), Decimal(0))
    by_sev = {s: sum(1 for f in findings if f["severity"] == s) for s in ("high", "medium", "low")}
    return {"findings": findings, "summary": {
        "rows_analyzed": len(rows), "total_amount": _money(total_amount), "currencies": currencies,
        "findings_count": len(findings), "by_severity": by_sev,
        "by_rule": {k: sum(1 for f in findings if f["rule_id"] == k) for k in RULES if any(f["rule_id"] == k for f in findings)},
        "total_exposure": _money(exposure), "control_totals": control_note or "not provided", "ruleset": RULESET_VERSION}}
