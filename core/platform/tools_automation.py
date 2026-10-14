"""Business-automation tools: read a spreadsheet, validate it, analyze it, generate a report, send it, record the result.

Each tool is a thin governed wrapper: all computation is in core.automation (pure and deterministic) and all I/O goes
through the connector interfaces (core.connectors). They run only through the operation pipeline, so argument
validation, agent/role authorization, policy, approval, idempotency and audit apply to every call.

Sensitive-report rule: a report is always stored as `confidential`. Sending a confidential attachment requires human
approval that is bound to the exact bytes being sent (see email_policy); changing the report after approval blocks the send."""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.automation import analysis, report, tables, validation
from core.connectors import get_email_connector
from core.connectors.base import Attachment, EmailMessage, EmailPermanentError, EmailTransientError, EmailUnknownOutcome
from core.platform import audit, config, files
from core.platform.db import session_factory
from core.platform.models import Approval, EmailDelivery, Run, StoredFile, utcnow
from core.platform.tools import Strict, ToolContext, ToolResult, ToolSpec, TransientToolError, register

AUDIT_ROLES = ("manager", "director", "controller", "admin")


class Out(BaseModel):
    model_config = ConfigDict(extra="allow")


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return format(v, "f")
    return v


def _can_read(row: StoredFile, ctx: ToolContext) -> Optional[str]:
    """Uploads are private to the uploader; run artifacts belong to their run. Anything else is refused."""
    if row.run_id is not None:
        return None if row.run_id == ctx.run_id else "That file belongs to a different run."
    return None if row.uploaded_by == ctx.user_id else "That file was uploaded by someone else."


def _fail(msg: str, cls: str = "validation_error") -> ToolResult:
    return ToolResult(False, {}, msg, failure_class=cls)


def _artifact(db, ctx: ToolContext, role: str, name: str, data: bytes, content_type: str, kind: str, sensitivity="internal", meta=None) -> StoredFile:
    return files.save(db, name=name, data=data, kind=kind, content_type=content_type, user_id=ctx.user_id, run_id=ctx.run_id,
                      node_id=ctx.node_id, sensitivity=sensitivity, meta={**(meta or {}), "role": role},
                      file_id=files.artifact_id(ctx.run_id, ctx.node_id, ctx.epoch, role))


def _json_artifact(db, ctx, role, name, payload: dict, sensitivity="internal") -> StoredFile:
    return _artifact(db, ctx, role, name, json.dumps(payload, default=str, separators=(",", ":")).encode(), "application/json", "dataset", sensitivity)


def _load_json(db, ctx, file_id: str) -> tuple[Optional[dict], Optional[ToolResult]]:
    try:
        row, data = files.load(db, file_id)
    except FileNotFoundError as exc:
        return None, _fail(str(exc))
    except files.FileIntegrityError as exc:
        return None, _fail(str(exc), "execution_failure")
    refused = _can_read(row, ctx)
    if refused:
        return None, _fail(refused, "policy_rejection")
    return json.loads(data), None


# ============================================================ 1. read
class FileReadIn(Strict):
    file_id: str = Field(min_length=3, max_length=60)
    sheet: Optional[str] = Field(default=None, max_length=120)


class ReadOut(Out):
    file_id: str
    name: str
    sheet: str
    sheets: list[str]
    columns: list[str]
    row_count: int
    header_row: int
    preview: list[dict]
    source_sha256: str


def _file_read_table(ctx: ToolContext, a: dict) -> ToolResult:
    db = session_factory()()
    try:
        try:
            row, data = files.load(db, a["file_id"])
        except FileNotFoundError as exc:
            return _fail(str(exc))
        except files.FileIntegrityError as exc:
            return _fail(str(exc), "execution_failure")
        refused = _can_read(row, ctx)
        if refused:
            return _fail(refused, "policy_rejection")
        if row.kind != "upload":
            return _fail("Only uploaded spreadsheets or CSV files can be read here.")
        try:
            t = tables.read_table(data, row.name, a.get("sheet"))
        except tables.TableError as exc:
            return _fail(f"{row.name}: {exc}")
        preview = [{"_row": n, **{c: _jsonable(v) for c, v in vals.items()}} for n, vals in t.rows[:5]]
        return ToolResult(True, {"file_id": row.id, "name": row.name, "sheet": t.sheet, "sheets": t.sheets, "columns": t.columns,
                                 "row_count": len(t.rows), "header_row": t.header_row, "preview": preview, "source_sha256": row.sha256},
                          evidence=[f"{row.name}#{t.sheet}", f"sha256:{row.sha256[:12]}"])
    finally:
        db.close()


# ============================================================ 2. validate
class DataValidateIn(Strict):
    file_id: str = Field(min_length=3, max_length=60)
    sheet: Optional[str] = Field(default=None, max_length=120)
    schema_: Optional[dict] = Field(default=None, alias="schema")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ValidateOut(Out):
    dataset_file_id: str
    rows_read: int
    rows_valid: int
    rows_quarantined: int
    error_total: int
    errors: list[dict]
    quarantined_rows: list[int]
    columns: list[str]
    source: dict


def _data_validate(ctx: ToolContext, a: dict) -> ToolResult:
    db = session_factory()()
    try:
        try:
            schema = validation.parse_schema(a.get("schema") or a.get("schema_") or validation.AUDIT_SCHEMA)
        except ValueError as exc:
            return _fail(f"The validation schema is invalid: {exc}")
        try:
            row, data = files.load(db, a["file_id"])
        except FileNotFoundError as exc:
            return _fail(str(exc))
        except files.FileIntegrityError as exc:
            return _fail(str(exc), "execution_failure")
        refused = _can_read(row, ctx)
        if refused:
            return _fail(refused, "policy_rejection")
        try:
            t = tables.read_table(data, row.name, a.get("sheet"))
        except tables.TableError as exc:
            return _fail(f"{row.name}: {exc}")
        v = validation.validate_table(t, schema)
        if v["blocking"]:
            return ToolResult(False, {"blocking": v["blocking"], "errors": v["errors"][:50]},
                              "Data validation failed: " + " ".join(v["blocking"]), failure_class="validation_error")
        source = {"file_id": row.id, "name": row.name, "sha256": row.sha256, "sheet": t.sheet}
        art = _json_artifact(db, ctx, "dataset", "validated-dataset.json",
                             {"schema_version": 1, "source": source, "columns": v["columns"], "rows": v["rows"],
                              "quarantined": v["quarantined"], "counts": v["counts"]})
        c = v["counts"]
        return ToolResult(True, {"dataset_file_id": art.id, "rows_read": c["rows_read"], "rows_valid": c["rows_valid"],
                                 "rows_quarantined": c["rows_quarantined"], "error_total": v["error_total"], "errors": v["errors"][:50],
                                 "quarantined_rows": [q["row"] for q in v["quarantined"]][:200], "columns": v["columns"], "source": source},
                          evidence=[f"{row.name}#{t.sheet}", f"{c['rows_valid']} valid rows"])
    finally:
        db.close()


# ============================================================ 3. analyze
class AuditAnalyzeIn(Strict):
    dataset_file_id: str = Field(min_length=3, max_length=60)
    rules: dict = Field(default_factory=dict)
    expected_total: Optional[Decimal] = None
    expected_count: Optional[int] = Field(default=None, ge=0)


class AnalyzeOut(Out):
    findings_file_id: str
    findings_count: int
    high_count: int
    medium_count: int
    low_count: int
    total_exposure: str
    total_amount: str
    rows_analyzed: int
    top_findings: list[dict]
    source: dict


def _audit_analyze(ctx: ToolContext, a: dict) -> ToolResult:
    db = session_factory()()
    try:
        ds, err = _load_json(db, ctx, a["dataset_file_id"])
        if err:
            return err
        try:
            cfg = {**(a.get("rules") or {})}
            if a.get("expected_total") is not None:
                cfg["expected_total"] = a["expected_total"]
            if a.get("expected_count") is not None:
                cfg["expected_count"] = a["expected_count"]
            rules = analysis.AuditRules.model_validate(cfg)
            out = analysis.analyze(ds["rows"], rules, ds["source"])
        except ValueError as exc:
            return _fail(f"Analysis could not run: {exc}")
        s = out["summary"]
        art = _json_artifact(db, ctx, "findings", "findings.json",
                             {"summary": s, "findings": out["findings"], "rules": json.loads(rules.model_dump_json()), "source": ds["source"]})
        top = [{"id": f["id"], "rule_id": f["rule_id"], "severity": f["severity"], "title": f["title"], "rows": f["rows"]} for f in out["findings"][:10]]
        return ToolResult(True, {"findings_file_id": art.id, "findings_count": s["findings_count"], "high_count": s["by_severity"]["high"],
                                 "medium_count": s["by_severity"]["medium"], "low_count": s["by_severity"]["low"],
                                 "total_exposure": s["total_exposure"], "total_amount": s["total_amount"], "rows_analyzed": s["rows_analyzed"],
                                 "top_findings": top, "source": ds["source"]},
                          evidence=[f"{f['id']} rows {f['rows']}" for f in out["findings"][:20]] or [f"{s['rows_analyzed']} rows analysed, no findings"])
    finally:
        db.close()


# ============================================================ 4. report
class ReportIn(Strict):
    findings_file_id: str = Field(min_length=3, max_length=60)
    dataset_file_id: str = Field(min_length=3, max_length=60)
    title: str = Field(default="Audit report", min_length=1, max_length=160)
    prepared_for: str = Field(default="Audit committee", max_length=120)
    narrative: Optional[str] = Field(default=None, max_length=report.MAX_NARRATIVE + 1)
    narrative_cites: list[str] = Field(default_factory=list, max_length=100)


class ReportOut(Out):
    report_file_id: str
    report_sha256: str
    csv_file_id: str
    csv_sha256: str
    findings_count: int
    high_count: int
    medium_count: int
    low_count: int
    title: str
    size: int
    sensitivity: str


def _report_generate(ctx: ToolContext, a: dict) -> ToolResult:
    db = session_factory()()
    try:
        fnd, err = _load_json(db, ctx, a["findings_file_id"])
        if err:
            return err
        ds, err = _load_json(db, ctx, a["dataset_file_id"])
        if err:
            return err
        problem = report.validate_narrative(a.get("narrative"), a.get("narrative_cites") or [], fnd["findings"])
        if problem:
            return _fail(f"Narrative rejected: {problem}")
        html = report.render_html(title=a["title"], prepared_for=a["prepared_for"], run_id=ctx.run_id, generated_at=utcnow().isoformat(timespec="seconds") + "Z",
                                  source=fnd["source"], validation={**ds["counts"], "quarantined": ds["quarantined"]}, findings=fnd["findings"],
                                  summary=fnd["summary"], rules=fnd["rules"], narrative=a.get("narrative"), narrative_cites=a.get("narrative_cites") or [])
        csvb = report.findings_csv(fnd["findings"])
        meta = {"title": a["title"], "findings": fnd["summary"]["findings_count"]}
        rep = _artifact(db, ctx, "report", "audit-report.html", html, "text/html", "report", "confidential", meta)
        csvf = _artifact(db, ctx, "report_csv", "audit-findings.csv", csvb, "text/csv", "report_csv", "confidential", meta)
        s = fnd["summary"]
        return ToolResult(True, {"report_file_id": rep.id, "report_sha256": rep.sha256, "csv_file_id": csvf.id, "csv_sha256": csvf.sha256,
                                 "findings_count": s["findings_count"], "high_count": s["by_severity"]["high"], "medium_count": s["by_severity"]["medium"],
                                 "low_count": s["by_severity"]["low"], "title": a["title"], "size": len(html), "sensitivity": "confidential"},
                          evidence=[f"report {rep.id} sha256:{rep.sha256[:12]}", f"{s['findings_count']} findings traced to source rows"])
    finally:
        db.close()


# ============================================================ 5. email
class EmailSendIn(Strict):
    to: list[str] = Field(min_length=1, max_length=10)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=5000)
    attachments: list[str] = Field(default_factory=list, max_length=5)
    approval_id: Optional[str] = Field(default=None, max_length=60)

    @field_validator("to", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            import re
            return [x for x in re.split(r"[,;\s]+", v) if x]
        return v


class EmailOut(Out):
    delivery_id: str
    status: str
    mode: str
    recipients: list[str]
    message_id: str
    attempts: int
    attachment_ids: list[str]


def _delivery_id(ctx: ToolContext) -> str:
    return "dlv_" + hashlib.sha256(f"{ctx.run_id}|{ctx.node_id}|{ctx.epoch}".encode()).hexdigest()[:16]


def email_policy(tc, args: dict) -> Optional[dict]:
    """Confidential attachments need an approval gate bound to their exact content; otherwise a human must approve the send."""
    db = tc.db
    ids = args.get("attachments") or []
    rows = [db.get(StoredFile, i) for i in ids]
    if any(r is None or r.run_id != tc.run.id for r in rows):
        return {"allowed": False, "requires_human_approval": False, "risk_level": "high", "rule_id": "RULE-EMAIL-003",
                "reason": "Attachments must be files generated by this run; arbitrary stored files cannot be sent."}
    confidential = [r for r in rows if r.sensitivity == "confidential"]
    if not confidential:
        return None
    ap = db.get(Approval, args["approval_id"]) if args.get("approval_id") else None
    approved_shas = set()
    if ap is not None and ap.run_id == tc.run.id and ap.status == "approved" and ap.tool_name == "approval.gate":
        subject = (ap.params_snapshot or {}).get("subject") or {}
        approved_shas = {v for k, v in subject.items() if k.endswith("_sha256") and isinstance(v, str)}
    if approved_shas and all(r.sha256 in approved_shas for r in confidential):
        return {"allowed": True, "requires_human_approval": False, "risk_level": "medium", "rule_id": "RULE-EMAIL-002",
                "reason": f"Confidential attachment(s) match the exact content approved at review gate {ap.id}."}
    why = ("an approval was supplied but it does not cover this exact content" if ap is not None
           else "no approval review gate covering this content was supplied")
    return {"allowed": True, "requires_human_approval": True, "risk_level": "high", "rule_id": "RULE-EMAIL-001",
            "reason": f"Sending a confidential report needs human approval bound to its exact content: {why}."}


def _email_send(ctx: ToolContext, a: dict) -> ToolResult:
    db = session_factory()()
    try:
        did = _delivery_id(ctx)
        atts, shas, ids = [], [], []
        for fid in a.get("attachments") or []:
            try:
                row, data = files.load(db, fid)
            except (FileNotFoundError, files.FileIntegrityError) as exc:
                return _fail(str(exc), "validation_error")
            if row.run_id != ctx.run_id:
                return _fail("Attachments must be files generated by this run.", "policy_rejection")
            atts.append(Attachment(row.name, row.content_type, data))
            shas.append(f"{row.name}: sha256 {row.sha256}")
            ids.append(row.id)
        connector = get_email_connector()
        info = connector.info()
        dlv = db.get(EmailDelivery, did)
        if dlv is None:
            body = (a.get("body") or "") + ("\n\nAttachment integrity (SHA-256):\n" + "\n".join(shas) if shas else "")
            dlv = EmailDelivery(id=did, run_id=ctx.run_id, node_id=ctx.node_id, connector=info.id, mode=info.mode, sender=config.email_from(),
                                recipients=a["to"], subject=a["subject"], body_sha256=hashlib.sha256(body.encode()).hexdigest(),
                                attachments=ids, status="pending", attempts=0)
            db.add(dlv)
            db.commit()
        else:
            body = (a.get("body") or "") + ("\n\nAttachment integrity (SHA-256):\n" + "\n".join(shas) if shas else "")
        if dlv.status == "sent":   # defence in depth: the idempotency table normally prevents reaching this
            return ToolResult(True, _email_out(dlv))
        if not info.enabled:
            dlv.status, dlv.error = "failed", f"{info.name} is not enabled: {info.description}"
            db.commit()
            return _fail(dlv.error, "policy_rejection")
        dlv.attempts += 1
        db.commit()
        try:
            res = connector.send(EmailMessage(sender=dlv.sender, to=list(a["to"]), subject=a["subject"], body=body, attachments=atts))
        except EmailTransientError as exc:
            dlv.status, dlv.error = "failed", f"{exc} (nothing was sent; will retry if attempts remain)"
            db.commit()
            raise TransientToolError(f"{exc}. Nothing was sent.")
        except EmailPermanentError as exc:
            dlv.status, dlv.error = "failed", str(exc)
            db.commit()
            return _fail(f"Email was not sent: {exc}", "execution_failure")
        except EmailUnknownOutcome as exc:
            dlv.status, dlv.error = "unknown", str(exc)
            db.commit()
            return _fail(f"{exc} Verify with the recipient or mail server before re-sending.", "outcome_unknown")
        dlv.status, dlv.provider_message_id, dlv.sent_at, dlv.error = "sent", res.message_id, utcnow(), None
        db.commit()
        return ToolResult(True, _email_out(dlv), evidence=[f"delivery {dlv.id} ({dlv.mode})", f"message {res.message_id}"])
    finally:
        db.close()


def _email_out(d: EmailDelivery) -> dict:
    return {"delivery_id": d.id, "status": d.status, "mode": d.mode, "recipients": list(d.recipients), "message_id": d.provider_message_id or "",
            "attempts": d.attempts, "attachment_ids": list(d.attachments)}


# ============================================================ 6. record result
class RecordIn(Strict):
    outcome: str = Field(pattern="^(delivered|no_findings|failed|completed)$")
    summary: str = Field(default="", max_length=1000)
    data: dict = Field(default_factory=dict)


class RecordOut(Out):
    recorded: bool
    outcome: str
    result: dict


def _run_record_result(ctx: ToolContext, a: dict) -> ToolResult:
    db = session_factory()()
    try:
        run = db.get(Run, ctx.run_id)
        res = dict(run.result or {})
        rep = db.query(StoredFile).filter(StoredFile.run_id == ctx.run_id, StoredFile.kind == "report").order_by(StoredFile.created_at.desc()).first()
        dlv = db.query(EmailDelivery).filter(EmailDelivery.run_id == ctx.run_id).order_by(EmailDelivery.created_at.desc()).first()
        res.update({"outcome": a["outcome"], "summary": a["summary"], "data": a["data"], "recorded_at": utcnow().isoformat(timespec="seconds") + "Z",
                    "report": {"file_id": rep.id, "sha256": rep.sha256, "name": rep.name} if rep else None,
                    "delivery": {"id": dlv.id, "status": dlv.status, "mode": dlv.mode, "recipients": dlv.recipients, "attempts": dlv.attempts,
                                 "sent_at": dlv.sent_at.isoformat() + "Z" if dlv.sent_at else None} if dlv else None})
        run.result = res
        db.commit()
        audit.record(db, actor_type="agent", actor_id=ctx.agent_id, action="run.result_recorded", outcome="success", resource_type="run",
                     resource_id=ctx.run_id, run_id=ctx.run_id, detail={"outcome": a["outcome"], "report": res["report"] and res["report"]["file_id"],
                                                                         "delivery": res["delivery"] and res["delivery"]["status"]})
        return ToolResult(True, {"recorded": True, "outcome": a["outcome"], "result": res}, evidence=[f"result recorded: {a['outcome']}"])
    finally:
        db.close()


for _spec in [
    ToolSpec("file_read_table", "Read an uploaded .xlsx or .csv file and describe its sheet, columns and rows (read-only).", "read",
             ("spreadsheet_ingest",), FileReadIn, _file_read_table, "files", output_required=("file_id", "columns", "row_count"),
             output_model=ReadOut, allowed_roles=AUDIT_ROLES, timeout_s=60, max_retries=1, idempotent=True),
    ToolSpec("data_validate", "Validate a spreadsheet against a schema; writes a typed dataset artifact and lists every bad row.", "write",
             ("data_validation",), DataValidateIn, _data_validate, "files", output_required=("dataset_file_id",), output_model=ValidateOut,
             allowed_roles=AUDIT_ROLES, timeout_s=60, max_retries=1, idempotent=True),
    ToolSpec("audit_analyze", "Run the deterministic audit rules over a validated dataset; every finding cites its source rows.", "write",
             ("audit_analysis",), AuditAnalyzeIn, _audit_analyze, "files", output_required=("findings_file_id", "findings_count"),
             output_model=AnalyzeOut, allowed_roles=AUDIT_ROLES, timeout_s=60, max_retries=1, idempotent=True),
    ToolSpec("report_generate", "Render the audit report (HTML) and findings CSV as confidential artifacts.", "write",
             ("report_generation",), ReportIn, _report_generate, "files", output_required=("report_file_id", "report_sha256"),
             output_model=ReportOut, allowed_roles=AUDIT_ROLES, timeout_s=60, max_retries=1, idempotent=True),
    ToolSpec("email_send", "Send an email with run-generated attachments. Confidential attachments need approval bound to their content.", "write",
             ("report_delivery",), EmailSendIn, _email_send, "email", output_required=("delivery_id", "status"), output_model=EmailOut,
             allowed_roles=AUDIT_ROLES, timeout_s=60, max_retries=2, retry_transient_writes=True, policy_hook=email_policy),
    ToolSpec("run_record_result", "Record the workflow's outcome, report reference and delivery status on the run.", "write",
             ("record_keeping",), RecordIn, _run_record_result, "internal", output_required=("recorded",), output_model=RecordOut,
             allowed_roles=AUDIT_ROLES, timeout_s=30, max_retries=1, idempotent=True),
]:
    register(_spec)
