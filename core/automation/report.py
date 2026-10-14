"""Audit report rendering. The report is a self-contained HTML document (no scripts, no external resources, a CSP
that forbids both) plus a CSV of findings. Every dynamic value is HTML-escaped; every CSV cell that could be read
by a spreadsheet as a formula is neutralised. AI-written narrative, if any, is labelled as such and must cite
real finding ids."""
import csv
import html
import io
from typing import Optional

from core.automation.analysis import RULES, RULESET_VERSION

e = html.escape
MAX_NARRATIVE = 4000


def csv_safe(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def findings_csv(findings: list[dict]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["finding_id", "rule_id", "severity", "title", "source_rows", "transaction_ids", "amount_impact", "detail", "source_sha256", "source_sheet"])
    for f in findings:
        w.writerow([csv_safe(x) for x in (f["id"], f["rule_id"], f["severity"], f["title"], " ".join(map(str, f["rows"])),
                                         " ".join(str(t) for t in f["txn_ids"]), f["amount_impact"], f["detail"],
                                         f["source"].get("sha256", ""), f["source"].get("sheet", ""))])
    return out.getvalue().encode("utf-8")


def validate_narrative(narrative: Optional[str], cites: list[str], findings: list[dict]) -> Optional[str]:
    """AI narrative is accepted only if it is bounded and cites real finding ids (traceability). Returns an error or None."""
    if not narrative:
        return None
    if len(narrative) > MAX_NARRATIVE:
        return f"The narrative is longer than {MAX_NARRATIVE} characters."
    ids = {f["id"] for f in findings}
    if not cites:
        return "An AI narrative must cite the finding ids it is based on."
    bad = [c for c in cites if c not in ids]
    if bad:
        return f"The narrative cites finding id(s) that do not exist: {', '.join(bad)}."
    return None


def render_html(*, title: str, prepared_for: str, run_id: str, generated_at: str, source: dict, validation: dict,
                findings: list[dict], summary: dict, rules: dict, narrative: Optional[str], narrative_cites: list[str]) -> bytes:
    sev = summary["by_severity"]
    rows = []
    for f in findings:
        rows.append(
            f"<tr class='sev-{e(f['severity'])}'><td>{e(f['id'])}</td><td>{e(f['severity'])}</td><td><b>{e(f['title'])}</b><br>{e(f['detail'])}"
            f"<br><small>Rule {e(f['rule_id'])} · {e(f['rule'])}</small></td><td>{e(', '.join(map(str, f['rows'])) or 'whole dataset')}</td>"
            f"<td>{e(', '.join(str(t) for t in f['txn_ids']))}</td><td class='num'>{e(f['amount_impact'])}</td></tr>")
    quarantined = validation.get("quarantined", [])
    q_rows = "".join(f"<tr><td>{e(str(q['row']))}</td><td>{e('; '.join(x['column'] + ': ' + x['message'] for x in q['errors']))}</td></tr>" for q in quarantined[:200])
    rule_rows = "".join(f"<tr><td>{e(rid)}</td><td>{e(name)}</td><td>{e(sev_)}</td><td>{e(desc)}</td></tr>" for rid, (name, sev_, desc) in RULES.items())
    narr = ""
    if narrative:
        narr = (f"<h2>Narrative summary</h2><p class='ai'><b>AI-generated, not independently verified.</b> Based on findings "
                f"{e(', '.join(narrative_cites))}.</p><p>{e(narrative)}</p>")
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>{e(title)}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;color:#111}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}}th,td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#f1f5f9}}.num{{text-align:right;font-variant-numeric:tabular-nums}}.sev-high td:nth-child(2){{color:#991b1b;font-weight:600}}
.sev-medium td:nth-child(2){{color:#92400e;font-weight:600}}.meta{{color:#475569}}.ai{{background:#fef3c7;padding:6px 8px;border-radius:4px}}
.conf{{border:1px solid #991b1b;color:#991b1b;display:inline-block;padding:2px 8px;border-radius:4px;font-weight:600}}</style></head><body>
<p class="conf">CONFIDENTIAL — internal audit report</p>
<h1>{e(title)}</h1>
<p class="meta">Prepared for {e(prepared_for)} · generated {e(generated_at)} · workflow run {e(run_id)} · rules {e(RULESET_VERSION)}</p>
<h2>Summary</h2>
<table><tr><th>Findings</th><th>High</th><th>Medium</th><th>Low</th><th>Total exposure</th><th>Rows analysed</th><th>Dataset total</th></tr>
<tr><td class="num">{summary['findings_count']}</td><td class="num">{sev['high']}</td><td class="num">{sev['medium']}</td><td class="num">{sev['low']}</td>
<td class="num">{e(summary['total_exposure'])}</td><td class="num">{summary['rows_analyzed']}</td><td class="num">{e(summary['total_amount'])} {e(' / '.join(summary['currencies']))}</td></tr></table>
{narr}
<h2>Findings</h2>
{('<table><tr><th>ID</th><th>Severity</th><th>Finding</th><th>Source rows</th><th>Transactions</th><th>Impact</th></tr>' + ''.join(rows) + '</table>') if rows else '<p>No discrepancies were detected by the configured rules.</p>'}
<h2>Source and scope</h2>
<table><tr><th>File</th><td>{e(str(source.get('name', '')))}</td></tr><tr><th>SHA-256</th><td>{e(str(source.get('sha256', '')))}</td></tr>
<tr><th>Sheet</th><td>{e(str(source.get('sheet', '')))}</td></tr>
<tr><th>Rows read / valid / quarantined</th><td>{validation.get('rows_read', 0)} / {validation.get('rows_valid', 0)} / {validation.get('rows_quarantined', 0)}</td></tr>
<tr><th>Control totals</th><td>{e(summary['control_totals'])}</td></tr></table>
<h2>Data quality: rows excluded from analysis</h2>
{('<table><tr><th>Sheet row</th><th>Problem</th></tr>' + q_rows + '</table>') if q_rows else '<p>No rows were excluded.</p>'}
<h2>Method</h2>
<p>All figures are computed by deterministic rules with exact decimal arithmetic; thresholds apply to the stated amount with no currency conversion.
Configured thresholds: {e(', '.join(f'{k}={v}' for k, v in rules.items()))}.</p>
<table><tr><th>Rule</th><th>Name</th><th>Severity</th><th>What it checks</th></tr>{rule_rows}</table>
</body></html>"""
    return doc.encode("utf-8")
