"""Workflow execution engine.

Guarantees
- Runs execute a snapshot of the workflow definition, in dependency order.
- Every state change is persisted and emitted as a numbered event, so history survives
  browser refreshes and backend restarts.
- A node that needs human approval is parked: its side effect has NOT happened. The
  approval service releases it; the exact parameters that were reviewed are the ones executed.
- Side-effecting nodes are executed at most once. A node is claimed with an atomic
  `pending|awaiting_approval -> running` transition before the tool is called, so a retried
  resume request can never repeat an approved action. If the process dies mid-call, the node
  is marked failed with an "outcome unknown" error instead of being re-sent.
"""
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from core.governance.policy_engine import APPROVAL_SLOTS, GovernancePolicyEngine
from core.platform import audit, config
from core.platform.catalog import CATALOG
from core.platform.db import session_factory
from core.platform.models import Approval, ApprovalDecision, NodeRun, Run, RunEvent, User, Workflow, utcnow
from core.platform.redaction import redact_secrets
from core.platform.validation import REF, coerce_inputs, has_errors, topo_order, validate_definition

TERMINAL = {"completed", "failed", "rejected"}
NODE_DONE = {"completed", "failed", "skipped", "rejected"}
MAX_READ_RETRIES = 1

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hacfew-run")
_run_locks: dict[str, threading.Lock] = {}
_run_locks_guard = threading.Lock()
_retriever = None
_retriever_lock = threading.Lock()

# Platform roles that policy documents do not name explicitly are mapped for retrieval filtering.
RETRIEVAL_ROLE = {"controller": "finance_rep", "director": "manager"}


class RunRejected(Exception):
    """Raised when a run cannot be created (validation or input errors)."""

    def __init__(self, message: str, issues: Optional[list] = None):
        super().__init__(message)
        self.issues = issues or []


def _lock_for(run_id: str) -> threading.Lock:
    with _run_locks_guard:
        return _run_locks.setdefault(run_id, threading.Lock())


def get_retriever():
    global _retriever
    with _retriever_lock:
        if _retriever is None:
            from core.rag.retriever import HybridPolicyRetriever
            _retriever = HybridPolicyRetriever("data/policies")
        return _retriever


# ------------------------------------------------------------------ events
def emit(db: Session, run_id: str, type_: str, node_id: Optional[str] = None, data: Optional[dict] = None) -> int:
    """Append a numbered, redacted event. The counter is bumped atomically in the database."""
    db.execute(update(Run).where(Run.id == run_id).values(next_seq=Run.next_seq + 1))
    seq = db.query(Run.next_seq).filter(Run.id == run_id).scalar() - 1
    db.add(RunEvent(run_id=run_id, seq=seq, ts=utcnow(), type=type_, node_id=node_id,
                    data=redact_secrets(data or {})))
    db.commit()
    return seq


# ------------------------------------------------------------------ run creation
def create_run(db: Session, workflow: Workflow, raw_inputs: dict, user: User) -> Run:
    definition = workflow.definition
    issues = validate_definition(definition, user_role=user.role)
    if has_errors(issues):
        audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="run.rejected",
                     outcome="denied", resource_type="workflow", resource_id=workflow.id,
                     detail={"issues": [i for i in issues if i["severity"] == "error"][:10]})
        raise RunRejected("Workflow failed validation.", issues)
    inputs, errors = coerce_inputs(definition, raw_inputs or {})
    if errors:
        raise RunRejected("Invalid run inputs: " + "; ".join(errors))

    run = Run(id=f"run_{uuid.uuid4().hex[:12]}", workflow_id=workflow.id, workflow_name=workflow.name,
              workflow_version=workflow.version, definition_snapshot=definition,
              inputs=inputs, status="queued", started_by=user.id, started_by_role=user.role)
    db.add(run)
    db.flush()
    for n in definition["nodes"]:
        spec = CATALOG[n["type"]]
        agent = (n.get("params") or {}).get("agent") if spec.kind == "rag" else spec.agent
        db.add(NodeRun(run_id=run.id, node_id=n["id"], node_type=n["type"],
                       label=n.get("label") or spec.label, agent=agent or spec.agent, status="pending"))
    db.commit()
    emit(db, run.id, "run.created", data={"workflow_id": workflow.id, "workflow_version": workflow.version,
                                          "started_by": user.id, "inputs": inputs})
    audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="run.started",
                 outcome="success", resource_type="run", resource_id=run.id, run_id=run.id,
                 detail={"workflow_id": workflow.id, "workflow_version": workflow.version})
    return run


def submit(run_id: str) -> None:
    """Execute now (tests) or on a worker thread (server)."""
    if config.sync_execution():
        drive(run_id)
    else:
        _executor.submit(_safe_drive, run_id)


def _safe_drive(run_id: str) -> None:
    try:
        drive(run_id)
    except Exception as exc:  # last-resort guard: never leave a run silently "running"
        db = session_factory()()
        try:
            run = db.get(Run, run_id)
            if run and run.status not in TERMINAL:
                run.status, run.error, run.finished_at = "failed", f"Engine error: {exc}", utcnow()
                db.commit()
                emit(db, run_id, "run.failed", data={"error": f"Engine error: {exc}"})
        finally:
            db.close()


# ------------------------------------------------------------------ driving a run
def drive(run_id: str) -> None:
    with _lock_for(run_id):
        db = session_factory()()
        try:
            _drive_locked(db, run_id)
        finally:
            db.close()


def _drive_locked(db: Session, run_id: str) -> None:
    run = db.get(Run, run_id)
    if run is None or run.status in TERMINAL:
        return
    previous = run.status
    run.status = "running"
    db.commit()
    emit(db, run.id, "run.resumed" if previous == "awaiting_approval" else "run.started")

    definition = run.definition_snapshot
    nodes = {n["id"]: n for n in definition["nodes"]}
    parents: dict[str, list[str]] = {i: [] for i in nodes}
    for e in definition["edges"]:
        parents[e["target"]].append(e["source"])
    order = topo_order(definition["nodes"], definition["edges"]) or []
    runs = {nr.node_id: nr for nr in db.query(NodeRun).filter(NodeRun.run_id == run.id)}
    user = db.get(User, run.started_by)

    for node_id in order:
        nr = runs[node_id]
        db.refresh(nr)
        if nr.status in NODE_DONE or (nr.status == "running"):
            continue
        parent_status = [runs[p].status for p in parents[node_id]]
        if any(s in ("failed", "skipped", "rejected") for s in parent_status):
            _skip(db, run, nr, "Skipped because an upstream node did not complete.")
            continue
        if any(s != "completed" for s in parent_status):
            continue  # an upstream node is still waiting (e.g. on approval)
        outputs = {k: v.output or {} for k, v in runs.items() if v.status == "completed"}
        _run_node(db, run, nr, nodes[node_id], outputs, user)

    _finalize(db, run)


def _skip(db: Session, run: Run, nr: NodeRun, reason: str) -> None:
    nr.status, nr.error, nr.summary, nr.finished_at = "skipped", reason, reason, utcnow()
    db.commit()
    emit(db, run.id, "node.skipped", nr.node_id, {"reason": reason})


def _finalize(db: Session, run: Run) -> None:
    statuses = [n.status for n in db.query(NodeRun).filter(NodeRun.run_id == run.id)]
    if "running" in statuses:
        return
    if "awaiting_approval" in statuses:
        run.status = "awaiting_approval"
        db.commit()
        emit(db, run.id, "run.awaiting_approval")
        return
    if "pending" in statuses:
        return
    if "rejected" in statuses:
        run.status = "rejected"
        run.error = "A human approver rejected a required step."
    elif "failed" in statuses:
        run.status = "failed"
        failed = db.query(NodeRun).filter(NodeRun.run_id == run.id, NodeRun.status == "failed").first()
        run.error = f"Node '{failed.label or failed.node_id}' failed: {failed.error}"
    else:
        run.status = "completed"
    run.finished_at = utcnow()
    db.commit()
    emit(db, run.id, f"run.{run.status}", data={"error": run.error} if run.error else {})
    audit.record(db, actor_type="system", actor_id="engine", action=f"run.{run.status}", outcome=
                 "success" if run.status == "completed" else "failure", resource_type="run",
                 resource_id=run.id, run_id=run.id, detail={"error": run.error})


# ------------------------------------------------------------------ params
def resolve_params(params: dict, inputs: dict, outputs: dict[str, dict]) -> dict:
    def lookup(path: str) -> Any:
        parts = path.split(".")
        if parts[0] == "trigger":
            cur: Any = inputs
            rest = parts[1:]
        else:  # nodes.<id>.output.<field...>
            cur = outputs.get(parts[1])
            if cur is None:
                raise KeyError(f"node '{parts[1]}' has no output")
            rest = parts[3:]
        for key in rest:
            if not isinstance(cur, dict) or key not in cur:
                raise KeyError(f"'{path}' is not available")
            cur = cur[key]
        return cur

    def sub(value: Any) -> Any:
        if isinstance(value, str):
            whole = REF.fullmatch(value.strip())
            if whole:
                return lookup(whole.group(1))
            return REF.sub(lambda m: str(lookup(m.group(1))), value)
        if isinstance(value, dict):
            return {k: sub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [sub(v) for v in value]
        return value

    return sub(params)


def _coerce_param_types(spec, params: dict) -> dict:
    out = dict(params)
    for p in spec.params:
        if p.name not in out:
            if p.default is not None:
                out[p.name] = p.default
            continue
        v = out[p.name]
        if p.type == "number":
            out[p.name] = float(v)
        elif p.type == "boolean" and not isinstance(v, bool):
            out[p.name] = str(v).lower() == "true"
        elif p.type == "string" or p.type == "text":
            out[p.name] = str(v)
    return out


# ------------------------------------------------------------------ node execution
def _claim(db: Session, nr: NodeRun, from_status: str) -> bool:
    """Atomic state transition; the single point that prevents double execution."""
    res = db.execute(update(NodeRun).where(NodeRun.id == nr.id, NodeRun.status == from_status)
                     .values(status="running", attempts=NodeRun.attempts + 1, started_at=utcnow()))
    db.commit()
    db.refresh(nr)
    return res.rowcount == 1


def _fail(db: Session, run: Run, nr: NodeRun, error: str, summary: Optional[str] = None) -> None:
    nr.status, nr.error, nr.finished_at = "failed", error, utcnow()
    nr.summary = summary or error
    db.commit()
    emit(db, run.id, "node.failed", nr.node_id, {"error": error})


def _complete(db: Session, run: Run, nr: NodeRun, output: dict, summary: str, latency_ms: int) -> None:
    nr.status, nr.output, nr.summary, nr.finished_at = "completed", redact_secrets(output), summary, utcnow()
    nr.latency_ms = (nr.latency_ms or 0) + latency_ms
    db.commit()
    emit(db, run.id, "node.completed", nr.node_id, {"latency_ms": nr.latency_ms, "summary": summary})


def _run_node(db: Session, run: Run, nr: NodeRun, node: dict, outputs: dict, user: User) -> None:
    spec = CATALOG[node["type"]]
    approval: Optional[Approval] = None

    if nr.status == "awaiting_approval":
        approval = db.query(Approval).filter(Approval.run_id == run.id, Approval.node_id == nr.node_id).first()
        if approval is None or approval.status == "pending":
            return
        if approval.status == "rejected":
            rej = (db.query(ApprovalDecision).filter(ApprovalDecision.approval_id == approval.id,
                                                     ApprovalDecision.decision == "reject").first())
            who = db.get(User, rej.approver_id).display_name if rej else "an approver"
            nr.status, nr.finished_at = "rejected", utcnow()
            nr.error = f"Rejected by {who}" + (f": {rej.comment}" if rej and rej.comment else "")
            nr.summary = nr.error
            db.commit()
            emit(db, run.id, "node.rejected", nr.node_id, {"reason": nr.error})
            return
        if not _claim(db, nr, "awaiting_approval"):
            return  # another resume already took it: this is what makes retries safe
        emit(db, run.id, "node.resumed", nr.node_id, {"approval_id": approval.id})
    else:
        if not _claim(db, nr, "pending"):
            return
        emit(db, run.id, "node.started", nr.node_id, {"type": nr.node_type, "agent": nr.agent})

    t0 = time.perf_counter()
    try:
        if spec.kind == "trigger":
            _complete(db, run, nr, dict(run.inputs), "Workflow started with the supplied inputs.", 0)
            return

        if approval is not None:
            params = dict(approval.params_snapshot)  # exactly what the approvers reviewed
            nr.input = redact_secrets(params)
        else:
            params = _coerce_param_types(spec, resolve_params(node.get("params") or {}, run.inputs, outputs))
            nr.input = redact_secrets(params)
            db.commit()

        if spec.kind == "rag":
            _run_rag(db, run, nr, spec, params, t0)
        else:
            _run_tool(db, run, nr, spec, params, user, approval, t0)
    except KeyError as exc:
        _fail(db, run, nr, f"Could not resolve a parameter reference: {exc.args[0]}")
    except Exception as exc:
        # A side-effecting tool may or may not have taken effect; say so rather than guess.
        note = " Outcome unknown; verify in the target system before retrying." if spec.side_effect else ""
        _fail(db, run, nr, f"Unexpected error: {exc}.{note}")


def _run_rag(db: Session, run: Run, nr: NodeRun, spec, params: dict, t0: float) -> None:
    agent = params.get("agent", "finance")
    if agent not in ("hr", "finance", "it"):
        return _fail(db, run, nr, f"Unknown agent '{agent}'.")
    nr.agent = agent
    role = RETRIEVAL_ROLE.get(run.started_by_role, run.started_by_role)
    last_error: Optional[str] = None
    for attempt in range(1 + MAX_READ_RETRIES):
        call_t = time.perf_counter()
        emit(db, run.id, "tool.call", nr.node_id, {"tool": "rag_retrieve_policy", "agent": agent,
                                                   "params": {"query": params["query"]}, "attempt": attempt + 1})
        try:
            res = get_retriever().retrieve(params["query"], user_role=role)
            ms = int((time.perf_counter() - call_t) * 1000)
            nr.tool_calls = (nr.tool_calls or []) + [{"tool": "rag_retrieve_policy", "success": True, "latency_ms": ms}]
            emit(db, run.id, "tool.result", nr.node_id, {"tool": "rag_retrieve_policy", "success": True,
                                                         "latency_ms": ms, "abstained": res.abstain})
            out = {"retrieved_chunks": len(res.results), "citations": res.citations,
                   "top_score": round(res.top_score, 4), "abstained": res.abstain, "context": res.context_for_prompt}
            summary = (f"Retrieved {len(res.results)} passage(s); top score {res.top_score:.2f}."
                       if not res.abstain else f"No grounded answer: {res.escalation_reason}")
            nr.policy = {"allowed": True, "risk_level": "low", "rule_id": "RULE-READ-001",
                         "reason": "Read-only query.", "requires_human_approval": False}
            _complete(db, run, nr, out, summary, int((time.perf_counter() - t0) * 1000))
            return
        except Exception as exc:
            last_error = str(exc)
            nr.attempts += 1
            db.commit()
            emit(db, run.id, "node.retry", nr.node_id, {"attempt": attempt + 1, "error": last_error})
    _fail(db, run, nr, f"Retrieval failed after retries: {last_error}")


def _approver_label(db: Session, approval: Approval) -> str:
    rows = db.query(ApprovalDecision).filter(ApprovalDecision.approval_id == approval.id,
                                             ApprovalDecision.decision == "approve").all()
    return ", ".join(f"{db.get(User, r.approver_id).display_name} ({r.approver_role})" for r in rows)


def _run_tool(db: Session, run: Run, nr: NodeRun, spec, params: dict, user: User,
              approval: Optional[Approval], t0: float) -> None:
    from core.tools.enterprise_tools import TOOL_REGISTRY

    # 1. Attribute-based checks on the human who started the run (server-side, not client-claimed).
    if user.role not in spec.allowed_roles:
        return _deny(db, run, nr, user, spec, f"Role '{user.role}' may not use '{spec.label}'.", "RULE-AUTHZ-ROLE")
    if (spec.tool == "erp_submit_expense" and user.role == "employee"
            and params.get("employee_id") != user.employee_id):
        return _deny(db, run, nr, user, spec, "Employees may only submit expenses for their own employee record.",
                     "RULE-AUTHZ-SELF")

    # 2. Deterministic policy decision (re-evaluated on resume against the approved snapshot).
    decision = GovernancePolicyEngine.evaluate_tool_execution(spec.agent, spec.tool, params, user_role=user.role)
    nr.policy = decision.model_dump(mode="json")
    db.commit()
    emit(db, run.id, "policy.decision", nr.node_id, nr.policy)
    audit.record(db, actor_type="agent", actor_id=spec.agent, action="policy.decision",
                 outcome="success" if decision.allowed else "denied", resource_type="tool", resource_id=spec.tool,
                 run_id=run.id, risk=decision.risk_level.value,
                 detail={"node": nr.node_id, "rule_id": decision.rule_id, "reason": decision.reason,
                         "requires_human_approval": decision.requires_human_approval})
    if not decision.allowed:
        return _fail(db, run, nr, decision.reason)

    # 3. Human approval gate: park the node, do NOT execute.
    if decision.requires_human_approval and approval is None:
        slots = APPROVAL_SLOTS.get(decision.rule_id or "", [["manager", "director", "admin"]])
        db.add(Approval(id=f"apr_{uuid.uuid4().hex[:12]}", run_id=run.id, node_id=nr.node_id, status="pending",
                        risk_level=decision.risk_level.value, rule_id=decision.rule_id, reason=decision.reason,
                        tool_name=spec.tool, agent=spec.agent, params_snapshot=params, required_slots=slots,
                        requested_by=run.started_by))
        nr.status = "awaiting_approval"
        nr.summary = f"Waiting for human approval. {decision.reason}"
        nr.latency_ms = int((time.perf_counter() - t0) * 1000)
        db.commit()
        emit(db, run.id, "approval.requested", nr.node_id, {"rule_id": decision.rule_id, "reason": decision.reason,
                                                             "required_slots": slots})
        emit(db, run.id, "node.awaiting_approval", nr.node_id)
        audit.record(db, actor_type="system", actor_id="engine", action="approval.requested", outcome="pending",
                     resource_type="run", resource_id=run.id, run_id=run.id, risk=decision.risk_level.value,
                     detail={"node": nr.node_id, "rule_id": decision.rule_id, "required_slots": slots})
        return

    # 4. Execute the tool (the node is already claimed as 'running': at-most-once).
    approved_by = _approver_label(db, approval) if approval else None
    kwargs = {"approved_by": approved_by} if (approval and spec.tool == "erp_submit_expense") else {}
    emit(db, run.id, "tool.call", nr.node_id, {"tool": spec.tool, "agent": spec.agent, "params": params,
                                               "approved_by": approved_by})
    call_t = time.perf_counter()
    resp = TOOL_REGISTRY[spec.tool](agent=spec.agent, params=params, **kwargs)
    ms = int((time.perf_counter() - call_t) * 1000)
    nr.tool_calls = (nr.tool_calls or []) + [{"tool": spec.tool, "success": resp.success, "latency_ms": ms,
                                              "error": resp.error}]
    emit(db, run.id, "tool.result", nr.node_id, {"tool": spec.tool, "success": resp.success, "latency_ms": ms,
                                                 "error": resp.error})
    audit.record(db, actor_type="agent", actor_id=spec.agent, action=f"tool.{spec.tool}",
                 outcome="success" if resp.success else "failure", resource_type="run", resource_id=run.id,
                 run_id=run.id, risk=decision.risk_level.value,
                 detail={"node": nr.node_id, "approved_by": approved_by, "error": resp.error})
    if not resp.success:
        return _fail(db, run, nr, resp.error or "Tool call failed.")
    data = resp.data or {}
    if data.get("status") == "awaiting_approval":
        return _fail(db, run, nr, "Tool reported an unresolved approval gate; refusing to continue.")
    summary = f"{spec.label}: {decision.reason}" + (f" Approved by {approved_by}." if approved_by else "")
    _complete(db, run, nr, data, summary, int((time.perf_counter() - t0) * 1000))


def _deny(db: Session, run: Run, nr: NodeRun, user: User, spec, reason: str, rule_id: str) -> None:
    nr.policy = {"allowed": False, "risk_level": spec.default_risk, "rule_id": rule_id, "reason": reason,
                 "requires_human_approval": False}
    db.commit()
    emit(db, run.id, "policy.decision", nr.node_id, nr.policy)
    audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="authz.denied",
                 outcome="denied", resource_type="tool", resource_id=spec.tool, run_id=run.id,
                 risk=spec.default_risk, detail={"node": nr.node_id, "rule_id": rule_id, "reason": reason})
    _fail(db, run, nr, reason)


# ------------------------------------------------------------------ restart recovery
def recover_interrupted_runs() -> int:
    """After a restart, resolve runs that were mid-flight. Awaiting-approval runs are durable
    and left alone. A read-only node that was running is safely re-run; a side-effecting node
    is failed as 'outcome unknown' and is never re-sent automatically."""
    db = session_factory()()
    count = 0
    try:
        for run in db.query(Run).filter(Run.status.in_(["queued", "running"])).all():
            for nr in db.query(NodeRun).filter(NodeRun.run_id == run.id, NodeRun.status == "running").all():
                spec = CATALOG.get(nr.node_type)
                if spec and not spec.side_effect:
                    nr.status = "pending"
                    db.commit()
                else:
                    _fail(db, run, nr, "Engine restarted while this step was executing. Outcome unknown; "
                                       "verify in the target system before retrying.")
            audit.record(db, actor_type="system", actor_id="engine", action="run.recovered", outcome="success",
                         resource_type="run", resource_id=run.id, run_id=run.id)
            submit(run.id)
            count += 1
    finally:
        db.close()
    return count
