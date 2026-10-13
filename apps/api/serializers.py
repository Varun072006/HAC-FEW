"""DB row -> API model conversion. Every outbound execution payload passes through view_for()."""
from typing import Optional

from sqlalchemy.orm import Session

from apps.api import schemas as s
from core.platform import approvals as approval_svc
from core.platform.models import Approval, ApprovalDecision, NodeRun, Run, User, Workflow
from core.platform.redaction import view_for
from core.platform.security import permissions_for
from core.platform.validation import has_errors, trigger_fields, validate_definition


def can_pii(user: User) -> bool:
    return "pii:read" in permissions_for(user.role)


def user_out(u: User) -> s.UserOut:
    return s.UserOut(id=u.id, username=u.username, display_name=u.display_name, role=u.role,
                     employee_id=u.employee_id, permissions=sorted(permissions_for(u.role)))


def _name(db: Session, user_id: str) -> str:
    u = db.get(User, user_id)
    return u.display_name if u else user_id


def workflow_summary(w: Workflow) -> s.WorkflowSummary:
    return s.WorkflowSummary(id=w.id, name=w.name, description=w.description, version=w.version,
                             template_id=w.template_id, node_count=len(w.definition.get("nodes", [])),
                             created_by=w.created_by, updated_at=w.updated_at)


def workflow_detail(w: Workflow, role: Optional[str]) -> s.WorkflowDetail:
    issues = validate_definition(w.definition, user_role=role)
    base = workflow_summary(w).model_dump()
    return s.WorkflowDetail(**base, definition=s.WorkflowDefinition(**w.definition), created_at=w.created_at,
                            validation=s.ValidationResult(valid=not has_errors(issues), issues=issues),
                            trigger_fields=trigger_fields(w.definition))


def run_summary(db: Session, r: Run) -> s.RunSummary:
    return s.RunSummary(id=r.id, workflow_id=r.workflow_id, workflow_name=r.workflow_name,
                        workflow_version=r.workflow_version, status=r.status, started_by=r.started_by,
                        started_by_name=_name(db, r.started_by), created_at=r.created_at,
                        finished_at=r.finished_at, error=r.error)


def node_run_out(n: NodeRun, viewer: User) -> s.NodeRunOut:
    pii = can_pii(viewer)
    return s.NodeRunOut(
        node_id=n.node_id, node_type=n.node_type, label=n.label, agent=n.agent, status=n.status,
        attempts=n.attempts, input=view_for(n.input, pii) if n.input else None,
        output=view_for(n.output, pii) if n.output else None, error=n.error,
        policy=s.PolicyDecisionOut(**n.policy) if n.policy else None,
        tool_calls=[s.ToolCallOut(**c) for c in (n.tool_calls or [])], summary=n.summary,
        started_at=n.started_at, finished_at=n.finished_at, latency_ms=n.latency_ms)


def approval_out(db: Session, a: Approval, viewer: User) -> s.ApprovalOut:
    run = db.get(Run, a.run_id)
    node = (run.definition_snapshot or {}).get("nodes", []) if run else []
    label = next((n.get("label") for n in node if n["id"] == a.node_id), None)
    decisions = db.query(ApprovalDecision).filter(ApprovalDecision.approval_id == a.id)\
        .order_by(ApprovalDecision.id.asc()).all()
    return s.ApprovalOut(
        id=a.id, run_id=a.run_id, workflow_name=run.workflow_name if run else "", node_id=a.node_id,
        node_label=label, status=a.status, risk_level=a.risk_level, rule_id=a.rule_id, reason=a.reason,
        tool_name=a.tool_name, agent=a.agent, params=view_for(a.params_snapshot, can_pii(viewer)),
        required_slots=a.required_slots, filled_slots=sorted(approval_svc.filled_slots(db, a)),
        requested_by=a.requested_by, requested_by_name=_name(db, a.requested_by), requested_at=a.requested_at,
        decided_at=a.decided_at,
        decisions=[s.ApprovalDecisionOut(approver_id=d.approver_id, approver_name=_name(db, d.approver_id),
                                         approver_role=d.approver_role, decision=d.decision, comment=d.comment,
                                         decided_at=d.decided_at) for d in decisions],
        can_decide=approval_svc.can_decide(db, a, viewer))
