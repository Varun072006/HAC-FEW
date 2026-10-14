"""Read-only registries and observability: agents, connectors, policies, audit, usage, overview, org."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from apps.api import schemas as s
from apps.api.serializers import run_summary, user_out
from core.governance.policy_engine import AGENT_TOOL_PERMISSIONS, APPROVAL_SLOTS, RULES_CATALOG
from core.platform import approvals as approval_svc
from core.platform import audit, config
from core.platform.catalog import CATALOG
from core.platform.db import get_session
from core.platform.models import Approval, AuditEvent, NodeRun, Run, User, Workflow
from core.platform.security import ROLE_PERMISSIONS, ROLES, require

router = APIRouter(tags=["Registry & observability"])

CONNECTORS = [
    ("hrms", "HRMS", "Employee records", ["hr.create_employee"], ["hrms_create_employee", "hrms_get_employee"]),
    ("erp", "ERP (Finance)", "Expenses and payroll", ["finance.submit_expense", "finance.setup_payroll"],
     ["erp_submit_expense", "erp_setup_payroll"]),
    ("ticketing", "IT ticketing", "Incidents and provisioning", ["it.create_ticket"], ["ticketing_create_ticket"]),
    ("notifications", "Notifications", "Email dispatch", ["notify.send_email"], ["notifications_send_email"]),
]


def _usage_by_type(db: Session) -> dict[str, tuple[int, int]]:
    failed = func.sum(case((NodeRun.status == "failed", 1), else_=0))
    rows = db.query(NodeRun.node_type, func.count(NodeRun.id), failed)        .filter(NodeRun.attempts > 0).group_by(NodeRun.node_type).all()
    return {t: (int(c), int(f or 0)) for t, c, f in rows}


@router.get("/connectors", response_model=list[s.ConnectorOut])
def connectors(db: Session = Depends(get_session), _: User = Depends(require("connector:read"))):
    from core.tools.enterprise_tools import mock_client
    usage = _usage_by_type(db)
    try:
        res = mock_client.get("/health")
        healthy, detail = res.status_code == 200, (res.json() if res.status_code == 200 else {})
    except Exception as exc:
        healthy, detail = False, {"error": str(exc)}
    out = []
    for cid, name, system, node_types, tools in CONNECTORS:
        calls = sum(usage.get(t, (0, 0))[0] for t in node_types)
        fails = sum(usage.get(t, (0, 0))[1] for t in node_types)
        out.append(s.ConnectorOut(
            id=cid, name=name, system=system, mode="In-process mock system",
            status="healthy" if healthy else "unreachable",
            detail=detail.get("database_counts", detail) if cid != "notifications" else {},
            tools=tools, calls=calls, failures=fails, configurable=False,
            note="Runs against the bundled mock enterprise systems. Editable connection settings need a "
                 "credential store, which this build does not have."))
    return out


@router.get("/policies", response_model=s.PolicyOverview)
def policies(_: User = Depends(require("policy:read"))):
    return s.PolicyOverview(
        agent_tool_permissions=AGENT_TOOL_PERMISSIONS, rules=RULES_CATALOG, approval_slots=APPROVAL_SLOTS,
        role_permissions={r: sorted(ROLE_PERMISSIONS[r]) for r in ROLES},
        node_role_access={t: list(n.allowed_roles) for t, n in CATALOG.items()})


@router.get("/audit", response_model=s.AuditPage)
def audit_log(action: Optional[str] = None, run_id: Optional[str] = None, outcome: Optional[str] = None,
              limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              db: Session = Depends(get_session), _: User = Depends(require("audit:read"))):
    q = db.query(AuditEvent)
    if action:
        q = q.filter(AuditEvent.action == action)
    if run_id:
        q = q.filter(AuditEvent.run_id == run_id)
    if outcome:
        q = q.filter(AuditEvent.outcome == outcome)
    total = q.count()
    rows = q.order_by(AuditEvent.id.desc()).offset(offset).limit(limit).all()
    return s.AuditPage(items=rows, total=total)


@router.get("/audit/verify", response_model=s.AuditVerify)
def audit_verify(db: Session = Depends(get_session), _: User = Depends(require("audit:read"))):
    return s.AuditVerify(**audit.verify_chain(db))


@router.get("/usage", response_model=s.UsageSummary)
def usage(db: Session = Depends(get_session), _: User = Depends(require("run:read_all"))):
    from core.platform.gateway import Usage
    rows = db.query(NodeRun.node_type, func.count(NodeRun.id), func.avg(NodeRun.latency_ms), func.max(NodeRun.latency_ms))\
        .filter(NodeRun.attempts > 0).group_by(NodeRun.node_type).all()
    by_type = _usage_by_type(db)
    items = [s.NodeTypeUsage(node_type=t, runs=int(c), failures=by_type.get(t, (0, 0))[1],
                             avg_latency_ms=round(float(a), 1) if a is not None else None,
                             max_latency_ms=int(m) if m is not None else None) for t, c, a, m in rows]
    tool_calls = tool_failures = 0
    for (calls,) in db.query(NodeRun.tool_calls).filter(NodeRun.tool_calls.isnot(None)).all():
        for c in calls or []:
            tool_calls += 1
            tool_failures += 0 if c.get("success") else 1
    total = Usage()
    for (u,) in db.query(NodeRun.usage).filter(NodeRun.usage.isnot(None)).all():
        total.add(Usage.from_dict(u))
    backed = total.calls > 0
    return s.UsageSummary(
        llm_backed=backed, llm_calls=total.calls, input_tokens=total.input_tokens, output_tokens=total.output_tokens,
        usage_source=total.source,
        note=("Token counts are summed from model calls recorded on task runs. 'provider' means the model server "
              "reported them; 'estimated' means they were derived from text length; no cost is computed."
              if backed else "No model-backed task has run yet, so there is no token usage to report. Scripted tasks "
                             "and tools make no model calls."),
        total_node_runs=sum(i.runs for i in items), by_node_type=items,
        tool_calls=tool_calls, tool_failures=tool_failures)


@router.get("/overview", response_model=s.Overview)
def overview(db: Session = Depends(get_session), user: User = Depends(require("run:read"))):
    from core.platform.security import permissions_for
    q = db.query(Run)
    if "run:read_all" not in permissions_for(user.role):
        q = q.filter(Run.started_by == user.id)
    by_status = {st: int(c) for st, c in q.with_entities(Run.status, func.count(Run.id)).group_by(Run.status).all()}
    pending = db.query(Approval).filter(Approval.status == "pending").all()
    mine = sum(1 for a in pending if approval_svc.can_decide(db, a, user))
    recent = q.order_by(Run.created_at.desc()).limit(6).all()
    return s.Overview(workflows=db.query(Workflow).count(), runs_total=sum(by_status.values()),
                      runs_by_status=by_status,
                      pending_approvals=len(pending) if "approval:decide" in permissions_for(user.role) else
                      sum(1 for a in pending if a.requested_by == user.id),
                      approvals_awaiting_you=mine, recent_runs=[run_summary(db, r) for r in recent])


@router.get("/org", response_model=s.OrgInfo)
def org(db: Session = Depends(get_session), _: User = Depends(require("org:admin"))):
    url = config.platform_database_url()
    safe = url.split("@")[-1] if "@" in url else url
    return s.OrgInfo(environment=config.env(), database=safe,
                     users=[user_out(u) for u in db.query(User).order_by(User.id)], roles=ROLES)
