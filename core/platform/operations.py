"""The one path every tool call takes.

    agent proposes -> arguments validated -> agent/role authorization -> policy decision ->
    human approval (parks the task) -> idempotency claim -> tool runs under a timeout ->
    output validated -> result persisted -> audit + event

Nothing an agent or model says can skip a step: authorization is computed from the registry snapshot
and the authenticated user's database role, and is re-checked on every call, including after approval.
The model never sees or supplies permissions."""
import hashlib
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.governance.policy_engine import APPROVAL_SLOTS, GovernancePolicyEngine
from core.platform import agent_registry, audit, tools
from core.platform.db import session_factory
from core.platform.events import emit
from core.platform.models import Approval, NodeRun, Run, ToolExecution, utcnow
from core.platform.redaction import redact_secrets
from core.platform.tools import ToolContext, TransientToolError

_tool_pool = ThreadPoolExecutor(max_workers=int(os.getenv("HACFEW_TOOL_WORKERS", "8")), thread_name_prefix="hacfew-tool")

# Failure classes (see docs/AGENT_RUNTIME.md)
VALIDATION, POLICY, EXECUTION, TIMEOUT, UNKNOWN = ("validation_error", "policy_rejection", "execution_failure",
                                                   "timeout", "outcome_unknown")


class Cancelled(Exception):
    pass


@dataclass
class TaskCtx:
    db: Session
    run: Run
    nr: NodeRun
    user: Any
    agent_id: str
    agent_cfg: dict
    department: str
    deadline: Optional[float] = None                 # time.monotonic() value
    sleep: Callable[[float], None] = time.sleep

    def cancelled(self) -> bool:
        flag = bool(self.db.query(Run.cancel_requested).filter(Run.id == self.run.id).scalar())
        self.db.commit()  # never idle inside a transaction: SQLite writers (tool threads) would queue behind it
        return flag

    def remaining(self) -> Optional[float]:
        return None if self.deadline is None else self.deadline - time.monotonic()

    def check_live(self) -> None:
        if self.cancelled():
            raise Cancelled()


@dataclass
class OpOutcome:
    status: str                                       # ok | failed | awaiting_approval
    tool: str
    effect: str = "read"
    data: dict = field(default_factory=dict)
    error: Optional[str] = None
    failure_class: Optional[str] = None
    evidence: list = field(default_factory=list)
    abstained: bool = False
    latency_ms: int = 0
    replayed: bool = False
    policy: Optional[dict] = None
    approval_id: Optional[str] = None
    approved_by: Optional[str] = None
    attempts: int = 1


def idempotency_key(run_id: str, node_id: str, op_index: int, tool: str) -> str:
    return hashlib.sha256(f"{run_id}|{node_id}|{op_index}|{tool}".encode()).hexdigest()


def backoff_delay(retry: dict, attempt: int) -> float:
    """Bounded exponential backoff: base * 2^attempt, never above backoff_max_s."""
    return min(retry["backoff_base_s"] * (2 ** attempt), retry["backoff_max_s"])


def sleep_interruptible(tc: TaskCtx, seconds: float) -> None:
    end = time.monotonic() + seconds
    while True:
        tc.check_live()
        left = end - time.monotonic()
        if left <= 0:
            return
        tc.sleep(min(left, 0.2))


def _deny(tc: TaskCtx, op_index: int, spec_name: str, effect: str, rule: str, reason: str, risk: str = "high") -> OpOutcome:
    policy = {"allowed": False, "risk_level": risk, "rule_id": rule, "reason": reason, "requires_human_approval": False}
    emit(tc.db, tc.run.id, "policy.decision", tc.nr.node_id, {**policy, "tool": spec_name, "op_index": op_index,
                                                              "agent": tc.agent_id})
    audit.record(tc.db, actor_type="agent", actor_id=tc.agent_id, action="authz.denied", outcome="denied",
                 resource_type="tool", resource_id=spec_name, run_id=tc.run.id, risk=risk,
                 detail={"node": tc.nr.node_id, "rule_id": rule, "reason": reason, "on_behalf_of": tc.user.id})
    return OpOutcome("failed", spec_name, effect, error=reason, failure_class=POLICY, policy=policy)


def authorize(tc: TaskCtx, spec, args: dict) -> Optional[tuple[str, str]]:
    """Agent-level and user-level authorization. Returns (rule_id, reason) when denied."""
    live = agent_registry.get_agent(tc.db, tc.agent_id)
    if live is None or live["status"] != "active":
        return "RULE-AGENT-STATE", f"Agent '{tc.agent_id}' is {live['status'] if live else 'missing'} and cannot act."
    cfg = tc.agent_cfg
    if spec.name not in cfg["allowed_tools"]:
        return "RULE-AGENT-TOOL", f"Agent '{tc.agent_id}' is not authorized to use '{spec.name}'."
    if not cfg["permissions"].get(spec.effect, False):
        return "RULE-AGENT-EFFECT", f"Agent '{tc.agent_id}' lacks {spec.effect} permission required by '{spec.name}'."
    if tc.user.role not in spec.allowed_roles:
        return "RULE-AUTHZ-ROLE", f"Role '{tc.user.role}' may not use '{spec.name}'."
    if spec.owner_field and tc.user.role == "employee" and args.get(spec.owner_field) != tc.user.employee_id:
        return "RULE-AUTHZ-SELF", "Employees may only act on their own employee record."
    return None


def decide_policy(tc: TaskCtx, spec, args: dict) -> dict:
    decision = GovernancePolicyEngine.evaluate_tool_execution(tc.department, spec.name, args, user_role=tc.user.role,
                                                              allowed_tools=tc.agent_cfg["allowed_tools"])
    d = decision.model_dump(mode="json")
    if d["allowed"] and spec.effect == "destructive" and not d["requires_human_approval"]:
        d.update(requires_human_approval=True, risk_level="high", rule_id="RULE-DESTRUCTIVE-001",
                 reason="Destructive operations always require human approval.")
    return d


def _finish_row(key: str, status: str, result: Optional[dict], error: Optional[str], ms: int) -> None:
    """Runs in the tool thread, so the outcome is recorded even if the waiting task timed out."""
    db = session_factory()()
    try:
        row = db.query(ToolExecution).filter(ToolExecution.idempotency_key == key).one()
        row.status, row.result, row.error, row.finished_at, row.latency_ms = status, redact_secrets(result), error, utcnow(), ms
        db.commit()
    finally:
        db.close()


def _run_tool(spec, ctx: ToolContext, args: dict, key: str):
    t0 = time.perf_counter()
    try:
        res = spec.handler(ctx, args)
    except TransientToolError as exc:
        _finish_row(key, "failed", None, f"transient: {exc}", int((time.perf_counter() - t0) * 1000))
        raise
    except Exception as exc:
        _finish_row(key, "failed", None, f"{type(exc).__name__}: {exc}", int((time.perf_counter() - t0) * 1000))
        raise
    ms = int((time.perf_counter() - t0) * 1000)
    _finish_row(key, "succeeded" if res.success else "failed", {"data": res.data, "evidence": res.evidence,
                                                                 "abstained": res.abstained} if res.success else None,
                res.error, ms)
    return res, ms


def execute_operation(tc: TaskCtx, op_index: int, tool_name: str, raw_args: Any, evidence: Optional[list] = None,
                      approval: Optional[Approval] = None) -> OpOutcome:
    db, run, nr = tc.db, tc.run, tc.nr
    spec = tools.get(tool_name)
    if spec is None:
        return OpOutcome("failed", tool_name, error=f"Unknown tool '{tool_name}'.", failure_class=VALIDATION)

    # 1. validate arguments (an approved operation re-uses the exact snapshot the approvers saw)
    try:
        args = spec.input_model.model_validate(approval.params_snapshot if approval else raw_args).model_dump()
    except ValidationError as exc:
        msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
        emit(db, run.id, "tool.rejected", nr.node_id, {"tool": tool_name, "op_index": op_index, "errors": msg})
        audit.record(db, actor_type="agent", actor_id=tc.agent_id, action="tool.invalid_arguments", outcome="denied",
                     resource_type="tool", resource_id=tool_name, run_id=run.id, detail={"node": nr.node_id, "errors": msg})
        return OpOutcome("failed", tool_name, spec.effect, error=f"Invalid arguments for {tool_name}: {msg}", failure_class=VALIDATION)

    # 2. authorization, immediately before the sensitive operation (and again after an approval)
    denied = authorize(tc, spec, args)
    if denied:
        return _deny(tc, op_index, tool_name, spec.effect, *denied)

    # 3. deterministic policy
    policy = decide_policy(tc, spec, args)
    emit(db, run.id, "policy.decision", nr.node_id, {**policy, "tool": tool_name, "op_index": op_index, "agent": tc.agent_id,
                                                      "effect": spec.effect})
    audit.record(db, actor_type="agent", actor_id=tc.agent_id, action="policy.decision",
                 outcome="success" if policy["allowed"] else "denied", resource_type="tool", resource_id=tool_name,
                 run_id=run.id, risk=policy["risk_level"],
                 detail={"node": nr.node_id, "rule_id": policy["rule_id"], "reason": policy["reason"],
                         "requires_human_approval": policy["requires_human_approval"], "effect": spec.effect})
    if not policy["allowed"]:
        return OpOutcome("failed", tool_name, spec.effect, error=policy["reason"], failure_class=POLICY, policy=policy)

    # 4. human approval gate: park, do not execute
    if policy["requires_human_approval"] and approval is None:
        slots = APPROVAL_SLOTS.get(policy["rule_id"] or "", [["manager", "director", "admin"]])
        apr = Approval(id=f"apr_{uuid.uuid4().hex[:12]}", run_id=run.id, node_id=nr.node_id, op_index=op_index,
                       status="pending", risk_level=policy["risk_level"], rule_id=policy["rule_id"],
                       reason=policy["reason"], tool_name=tool_name, agent=tc.agent_id, params_snapshot=args,
                       required_slots=slots, requested_by=run.started_by, evidence=redact_secrets(evidence or []))
        db.add(apr)
        db.commit()
        emit(db, run.id, "approval.requested", nr.node_id, {"approval_id": apr.id, "rule_id": policy["rule_id"],
                                                             "reason": policy["reason"], "required_slots": slots,
                                                             "tool": tool_name, "op_index": op_index})
        audit.record(db, actor_type="system", actor_id="engine", action="approval.requested", outcome="pending",
                     resource_type="run", resource_id=run.id, run_id=run.id, risk=policy["risk_level"],
                     detail={"node": nr.node_id, "rule_id": policy["rule_id"], "required_slots": slots,
                             "approval_id": apr.id, "op_index": op_index})
        return OpOutcome("awaiting_approval", tool_name, spec.effect, policy=policy, approval_id=apr.id)

    approved_by = _approver_label(db, approval) if approval else None
    tc.check_live()

    # 5. idempotency: one execution per (run, node, operation slot)
    key = idempotency_key(run.id, nr.node_id, op_index, tool_name)
    row = db.query(ToolExecution).filter(ToolExecution.idempotency_key == key).first()
    if row is not None:
        if row.status == "succeeded":
            payload = row.result or {}
            emit(db, run.id, "tool.replayed", nr.node_id, {"tool": tool_name, "op_index": op_index})
            return OpOutcome("ok", tool_name, spec.effect, data=payload.get("data", {}), evidence=payload.get("evidence", []),
                             abstained=payload.get("abstained", False), latency_ms=row.latency_ms or 0, replayed=True,
                             policy=policy, approved_by=approved_by)
        if spec.effect != "read":
            note = ("Outcome unknown: a previous attempt started this operation and its result was not recorded. "
                    "Verify in the target system before retrying." if row.status == "started"
                    else f"This operation already failed once and is not re-sent: {row.error}")
            return OpOutcome("failed", tool_name, spec.effect, error=note, policy=policy,
                             failure_class=UNKNOWN if row.status == "started" else EXECUTION)
        row.status, row.started_at = "started", utcnow()
        db.commit()
    else:
        db.add(ToolExecution(idempotency_key=key, run_id=run.id, node_id=nr.node_id, op_index=op_index, tool=tool_name,
                             effect=spec.effect, status="started", args=redact_secrets(args)))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return OpOutcome("failed", tool_name, spec.effect, failure_class=UNKNOWN, policy=policy,
                             error="Outcome unknown: a concurrent worker is executing this operation.")

    # 6. execute (reads may retry transient failures with bounded backoff; writes never auto-retry)
    retry = tc.agent_cfg["retry"]
    max_retries = min(spec.max_retries, retry["max_retries"]) if spec.effect == "read" else 0
    ctx = ToolContext(run.id, nr.node_id, tc.agent_id, tc.department, tc.user.role, tc.user.employee_id, approved_by)
    attempt = 0
    while True:
        left = tc.remaining()
        if left is not None and left <= 0:
            return _timeout(tc, spec, op_index, key, policy, "Task deadline reached before the tool call.")
        timeout = spec.timeout_s if left is None else min(spec.timeout_s, left)
        emit(db, run.id, "tool.call", nr.node_id, {"tool": tool_name, "agent": tc.agent_id, "effect": spec.effect,
                                                    "op_index": op_index, "params": args, "approved_by": approved_by,
                                                    "attempt": attempt + 1})
        fut = _tool_pool.submit(_run_tool, spec, ctx, args, key)
        db.commit()
        try:
            res, ms = fut.result(timeout=timeout)
            break
        except FutureTimeout:
            if spec.effect == "read" and attempt < max_retries:
                attempt += 1
                delay = backoff_delay(retry, attempt - 1)
                emit(db, run.id, "node.retry", nr.node_id, {"tool": tool_name, "attempt": attempt, "delay_s": delay,
                                                             "error": f"timed out after {timeout:.1f}s"})
                sleep_interruptible(tc, delay)
                continue
            return _timeout(tc, spec, op_index, key, policy, f"Tool '{tool_name}' timed out after {timeout:.1f}s.")
        except TransientToolError as exc:
            if spec.effect == "read" and attempt < max_retries:
                attempt += 1
                delay = backoff_delay(retry, attempt - 1)
                emit(db, run.id, "node.retry", nr.node_id, {"tool": tool_name, "attempt": attempt, "delay_s": delay,
                                                             "error": str(exc)[:200]})
                sleep_interruptible(tc, delay)
                continue
            emit(db, run.id, "tool.result", nr.node_id, {"tool": tool_name, "success": False, "error": str(exc)[:300],
                                                          "op_index": op_index})
            note = "" if spec.effect == "read" else " Outcome unknown; verify in the target system before retrying."
            return OpOutcome("failed", tool_name, spec.effect, error=f"{exc}{note}", policy=policy,
                             failure_class=EXECUTION if spec.effect == "read" else UNKNOWN, attempts=attempt + 1)
        except Exception as exc:
            note = "" if spec.effect == "read" else " Outcome unknown; verify in the target system before retrying."
            emit(db, run.id, "tool.result", nr.node_id, {"tool": tool_name, "success": False, "error": str(exc)[:300],
                                                          "op_index": op_index})
            return OpOutcome("failed", tool_name, spec.effect, error=f"Unexpected error: {exc}.{note}", policy=policy,
                             failure_class=EXECUTION if spec.effect == "read" else UNKNOWN)

    # 7. validate the result, record, audit
    missing = [k for k in spec.output_required if k not in (res.data or {})] if res.success else []
    ok = res.success and not missing
    emit(db, run.id, "tool.result", nr.node_id, {"tool": tool_name, "success": ok, "latency_ms": ms, "op_index": op_index,
                                                  "error": res.error or (f"output missing {missing}" if missing else None),
                                                  "abstained": res.abstained})
    audit.record(db, actor_type="agent", actor_id=tc.agent_id, action=f"tool.{tool_name}",
                 outcome="success" if ok else "failure", resource_type="run", resource_id=run.id, run_id=run.id,
                 risk=policy["risk_level"], detail={"node": nr.node_id, "approved_by": approved_by, "effect": spec.effect,
                                                    "error": res.error, "op_index": op_index})
    if missing:
        return OpOutcome("failed", tool_name, spec.effect, error=f"Tool output failed validation: missing {missing}.",
                         failure_class=VALIDATION, policy=policy, latency_ms=ms)
    if not res.success:
        return OpOutcome("failed", tool_name, spec.effect, error=res.error or "Tool call failed.", failure_class=EXECUTION,
                         policy=policy, latency_ms=ms, data=res.data or {})
    return OpOutcome("ok", tool_name, spec.effect, data=res.data or {}, evidence=list(res.evidence), abstained=res.abstained,
                     latency_ms=ms, policy=policy, approved_by=approved_by, attempts=attempt + 1)


def _timeout(tc: TaskCtx, spec, op_index: int, key: str, policy: dict, msg: str) -> OpOutcome:
    emit(tc.db, tc.run.id, "tool.result", tc.nr.node_id, {"tool": spec.name, "success": False, "error": msg, "op_index": op_index})
    if spec.effect != "read":
        return OpOutcome("failed", spec.name, spec.effect, failure_class=UNKNOWN, policy=policy,
                         error=msg + " Outcome unknown; verify in the target system before retrying.")
    return OpOutcome("failed", spec.name, spec.effect, failure_class=TIMEOUT, policy=policy, error=msg)


def _approver_label(db: Session, approval: Approval) -> str:
    from core.platform.models import ApprovalDecision, User
    rows = db.query(ApprovalDecision).filter(ApprovalDecision.approval_id == approval.id,
                                             ApprovalDecision.decision == "approve").all()
    return ", ".join(f"{db.get(User, r.approver_id).display_name} ({r.approver_role})" for r in rows)
