"""Human approval service. All authorization is decided here, on the server, from the
authenticated user's database record."""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.platform import audit
from core.platform.engine import emit
from core.platform.models import Approval, ApprovalDecision, User, utcnow
from core.platform.security import permissions_for


class ApprovalError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class DecisionResult:
    approval: Approval
    transitioned: Optional[str]  # "approved" | "rejected" when this call finalised the approval


def filled_slots(db: Session, approval: Approval) -> set[int]:
    rows = db.query(ApprovalDecision.slot_index).filter(
        ApprovalDecision.approval_id == approval.id, ApprovalDecision.decision == "approve").all()
    return {r[0] for r in rows if r[0] is not None}


def next_slot_for(db: Session, approval: Approval, role: str) -> Optional[int]:
    taken = filled_slots(db, approval)
    for idx, roles in enumerate(approval.required_slots):
        if idx not in taken and role in roles:
            return idx
    return None


def can_decide(db: Session, approval: Approval, user: User) -> bool:
    if approval.status != "pending" or "approval:decide" not in permissions_for(user.role):
        return False
    if approval.requested_by == user.id:
        return False
    if db.query(ApprovalDecision).filter(ApprovalDecision.approval_id == approval.id,
                                         ApprovalDecision.approver_id == user.id).first():
        return False
    return next_slot_for(db, approval, user.role) is not None


def decide(db: Session, approval_id: str, user: User, decision: str, comment: Optional[str]) -> DecisionResult:
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise ApprovalError(404, "Approval not found.")
    if approval.status != "pending":
        raise ApprovalError(409, f"This approval is already {approval.status}.")

    def deny(message: str, code: int = 403):
        audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="approval.decision_denied",
                     outcome="denied", resource_type="approval", resource_id=approval.id, run_id=approval.run_id,
                     risk=approval.risk_level, detail={"reason": message, "attempted": decision})
        raise ApprovalError(code, message)

    if "approval:decide" not in permissions_for(user.role):
        deny("Your role cannot decide approvals.")
    if approval.requested_by == user.id:
        deny("Separation of duties: you cannot decide an approval for a run you started.")
    if db.query(ApprovalDecision).filter(ApprovalDecision.approval_id == approval.id,
                                         ApprovalDecision.approver_id == user.id).first():
        raise ApprovalError(409, "You have already decided this approval.")
    slot = next_slot_for(db, approval, user.role)
    if slot is None:
        allowed = sorted({r for roles in approval.required_slots for r in roles})
        deny(f"No open approval slot for role '{user.role}'. Eligible roles: {', '.join(allowed)}.")

    try:
        db.add(ApprovalDecision(approval_id=approval.id, approver_id=user.id, approver_role=user.role,
                                decision=decision, comment=(comment or None),
                                slot_index=slot if decision == "approve" else None))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApprovalError(409, "A conflicting decision was recorded at the same time. Reload and retry.")

    transitioned: Optional[str] = None
    if decision == "reject":
        target = "rejected"
    elif len(filled_slots(db, approval)) >= len(approval.required_slots):
        target = "approved"
    else:
        target = None
    if target:
        res = db.execute(update(Approval).where(Approval.id == approval.id, Approval.status == "pending")
                         .values(status=target, decided_at=utcnow()))
        db.commit()
        if res.rowcount == 1:
            transitioned = target
    db.refresh(approval)

    audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="approval.decided",
                 outcome="success", resource_type="approval", resource_id=approval.id, run_id=approval.run_id,
                 risk=approval.risk_level,
                 detail={"decision": decision, "slot": slot, "comment": comment, "approval_status": approval.status,
                         "rule_id": approval.rule_id})
    emit(db, approval.run_id, "approval.decided", approval.node_id,
         {"approval_id": approval.id, "decision": decision, "approver": user.display_name,
          "approver_role": user.role, "approval_status": approval.status})
    return DecisionResult(approval=approval, transitioned=transitioned)
