"""Workflow execution engine: a dependency-aware, bounded-concurrency task-graph scheduler.

Scheduling rules (see docs/AGENT_RUNTIME.md)
- A node runs only when every upstream node is `completed`. If any upstream node failed, was skipped,
  rejected or cancelled, the node is `skipped` and never runs. There is no "run anyway" mode: a failed
  or empty dependency is never silently ignored.
- Independent ready nodes run in parallel on a worker pool, never exceeding the run's max_concurrency.
- A failed *required* node fails the run. A failed *optional* node does not: the run ends `partial`
  (its dependents are still skipped).
- A human rejection ends that path (`rejected`); independent paths still complete.
- Cancellation: no new node starts; running nodes stop at their next operation boundary; parked and
  pending nodes are cancelled together with their open approvals. An in-flight side effect is never
  interrupted midway.

Durability
- Every state change is persisted and emitted as a numbered event, so history survives browser
  refreshes and backend restarts. Nothing essential lives only in memory.
- Side effects run at most once: a node is claimed with an atomic `pending|awaiting_approval -> running`
  transition, and each operation holds a unique idempotency key. A retried resume request can never repeat
  an approved action. After a crash, a write whose outcome was not recorded is failed as
  "outcome unknown" instead of being re-sent. This is at-most-once delivery, not exactly-once: the mock
  systems offer no idempotency token of their own, so a crash between the call and the record cannot be
  distinguished from a call that never happened."""
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from core.platform import agent_registry, audit, config, tools
from core.platform.agent_runner import agent_entry, run_agent_task, run_budget
from core.platform.catalog import CATALOG
from core.platform.db import session_factory
from core.platform.events import emit
from core.platform.models import Approval, ApprovalDecision, NodeRun, Run, ToolExecution, User, Workflow, utcnow
from core.platform.nodes import cancel_node, complete_node, fail_node
from core.platform.operations import TaskCtx, execute_operation
from core.platform.params import coerce_param_types, resolve_params  # noqa: F401  (resolve_params re-exported)
from core.platform.planner import DEFAULT_CONSTRAINTS, SERVER_CAPS
from core.platform.redaction import redact_secrets
from core.platform.validation import ancestors, coerce_inputs, has_errors, topo_order, validate_definition

TERMINAL = {"completed", "partial", "failed", "rejected", "cancelled"}
BAD_UPSTREAM = ("failed", "skipped", "rejected", "cancelled")

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hacfew-run")          # one thread per driven run
_node_pool = ThreadPoolExecutor(max_workers=config.node_workers(), thread_name_prefix="hacfew-node")
_run_locks: dict[str, threading.Lock] = {}
_run_locks_guard = threading.Lock()


class RunRejected(Exception):
    """Raised when a run cannot be created (validation or input errors)."""

    def __init__(self, message: str, issues: Optional[list] = None):
        super().__init__(message)
        self.issues = issues or []


def _lock_for(run_id: str) -> threading.Lock:
    with _run_locks_guard:
        return _run_locks.setdefault(run_id, threading.Lock())


def get_retriever():
    return tools.get_retriever()


# ------------------------------------------------------------------ run creation
def _agents_used(definition: dict) -> set[str]:
    ids: set[str] = set()
    for n in definition["nodes"]:
        spec = CATALOG[n["type"]]
        if spec.kind == "agent":
            ids.add((n.get("params") or {}).get("agent_id", ""))
        elif spec.kind == "rag":
            ids.add((n.get("params") or {}).get("agent") or spec.agent)
        elif spec.agent:
            ids.add(spec.agent)
    return {i for i in ids if i}


def create_run(db: Session, workflow: Workflow, raw_inputs: dict, user: User, objective: Optional[str] = None,
               plan_id: Optional[str] = None, constraints: Optional[dict] = None) -> Run:
    definition = workflow.definition
    issues = validate_definition(definition, user_role=user.role, db=db)
    if has_errors(issues):
        audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="run.rejected",
                     outcome="denied", resource_type="workflow", resource_id=workflow.id,
                     detail={"issues": [i for i in issues if i["severity"] == "error"][:10]})
        raise RunRejected("Workflow failed validation.", issues)
    inputs, errors = coerce_inputs(definition, raw_inputs or {})
    if errors:
        raise RunRejected("Invalid run inputs: " + "; ".join(errors))

    budget = {**DEFAULT_CONSTRAINTS}
    for k, v in (constraints or {}).items():
        if k in budget:
            budget[k] = min(int(v), SERVER_CAPS[k])   # a request can lower a limit, never raise it past the server cap
    snapshot = agent_registry.snapshot_for(db, _agents_used(definition))

    run = Run(id=f"run_{uuid.uuid4().hex[:12]}", workflow_id=workflow.id, workflow_name=workflow.name,
              workflow_version=workflow.version, definition_snapshot=definition,
              inputs=inputs, status="queued", started_by=user.id, started_by_role=user.role,
              objective=objective, plan_id=plan_id, budget=budget, agent_snapshot=snapshot)
    db.add(run)
    db.flush()
    for n in definition["nodes"]:
        spec = CATALOG[n["type"]]
        params = n.get("params") or {}
        agent = params.get("agent_id") if spec.kind == "agent" else (params.get("agent") if spec.kind == "rag" else spec.agent)
        db.add(NodeRun(run_id=run.id, node_id=n["id"], node_type=n["type"],
                       label=n.get("label") or spec.label, agent=agent or spec.agent, status="pending"))
    db.commit()
    emit(db, run.id, "run.created", data={"workflow_id": workflow.id, "workflow_version": workflow.version,
                                          "started_by": user.id, "inputs": inputs, "objective": objective,
                                          "budget": budget, "plan_id": plan_id})
    audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="run.started",
                 outcome="success", resource_type="run", resource_id=run.id, run_id=run.id,
                 detail={"workflow_id": workflow.id, "workflow_version": workflow.version, "plan_id": plan_id})
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


def request_cancel(db: Session, run: Run, user: User) -> bool:
    """Ask a run to stop. Returns False if it is already finished."""
    if run.status in TERMINAL:
        return False
    run.cancel_requested = True
    db.commit()
    emit(db, run.id, "run.cancel_requested", data={"by": user.id})
    audit.record(db, actor_type="user", actor_id=user.id, actor_role=user.role, action="run.cancel_requested",
                 outcome="success", resource_type="run", resource_id=run.id, run_id=run.id)
    submit(run.id)
    return True


# ------------------------------------------------------------------ driving a run
def drive(run_id: str) -> None:
    with _lock_for(run_id):
        db = session_factory()()
        try:
            _drive_locked(db, run_id)
        finally:
            db.close()


def _approval_for(db: Session, run_id: str, nr: NodeRun) -> Optional[Approval]:
    idx = ((nr.checkpoint or {}).get("pending") or {}).get("index", 0)
    return db.query(Approval).filter(Approval.run_id == run_id, Approval.node_id == nr.node_id,
                                     Approval.op_index == idx).first()


def _drive_locked(db: Session, run_id: str) -> None:
    run = db.get(Run, run_id)
    if run is None or run.status in TERMINAL:
        return
    previous = run.status
    run.status = "running"
    db.commit()
    emit(db, run.id, "run.resumed" if previous == "awaiting_approval" else "run.started")

    definition = run.definition_snapshot
    parents: dict[str, list[str]] = {n["id"]: [] for n in definition["nodes"]}
    for e in definition["edges"]:
        parents[e["target"]].append(e["source"])
    order = topo_order(definition["nodes"], definition["edges"]) or []
    max_conc = max(1, min(run_budget(run)["max_concurrency"], SERVER_CAPS["max_concurrency"]))
    inflight: dict[Future, str] = {}
    cancelling = False

    while True:
        db.expire_all()
        run = db.get(Run, run_id)
        cancelling = bool(run.cancel_requested)
        runs = {nr.node_id: nr for nr in db.query(NodeRun).filter(NodeRun.run_id == run_id)}
        busy = set(inflight.values())
        if not cancelling:
            for node_id in order:
                nr = runs[node_id]
                if node_id in busy:
                    continue
                if nr.status == "pending":
                    states = [runs[p].status for p in parents[node_id]]
                    if any(s in BAD_UPSTREAM for s in states):
                        _skip(db, run, nr, "Skipped because an upstream node did not complete.")
                        continue
                    ready = all(s == "completed" for s in states)
                    decided = ((nr.checkpoint or {}).get("pending") is not None
                               and (_approval_for(db, run_id, nr) or Approval(status="pending")).status == "approved")
                    if (ready or decided) and len(inflight) < max_conc:
                        inflight[_node_pool.submit(_node_worker, run_id, node_id)] = node_id
                elif nr.status == "awaiting_approval" and len(inflight) < max_conc:
                    a = _approval_for(db, run_id, nr)
                    if a is not None and a.status in ("approved", "rejected", "cancelled"):
                        inflight[_node_pool.submit(_node_worker, run_id, node_id)] = node_id
        db.commit()  # end the read transaction: workers must be able to write
        if not inflight:
            break
        done, _ = wait(list(inflight), timeout=1.0, return_when=FIRST_COMPLETED)
        for f in done:
            node_id = inflight.pop(f)
            if f.exception() is not None:
                nr = db.query(NodeRun).filter(NodeRun.run_id == run_id, NodeRun.node_id == node_id).one()
                if nr.status in ("running", "pending", "awaiting_approval"):
                    fail_node(db, run, nr, f"Engine error: {f.exception()}")

    db.expire_all()
    run = db.get(Run, run_id)
    if run.cancel_requested:
        _apply_cancel(db, run)
    _finalize(db, run, definition)


def _node_worker(run_id: str, node_id: str) -> None:
    db = session_factory()()
    try:
        run = db.get(Run, run_id)
        nr = db.query(NodeRun).filter(NodeRun.run_id == run_id, NodeRun.node_id == node_id).one()
        node = next(n for n in run.definition_snapshot["nodes"] if n["id"] == node_id)
        outputs = {r.node_id: r.output or {} for r in db.query(NodeRun).filter(NodeRun.run_id == run_id,
                                                                              NodeRun.status == "completed")}
        anc = ancestors(node_id, run.definition_snapshot["edges"])
        upstream = [{"node": k, "evidence": (outputs[k].get("evidence") or [])[:10]} for k in sorted(anc)
                    if k in outputs and outputs[k].get("evidence")]
        db.commit()
        user = db.get(User, run.started_by)
        _run_node(db, run, nr, node, outputs, user, upstream)
    finally:
        db.close()


def _skip(db: Session, run: Run, nr: NodeRun, reason: str) -> None:
    nr.status, nr.error, nr.summary, nr.finished_at, nr.failure_class = "skipped", reason, reason, utcnow(), "upstream_failed"
    db.commit()
    emit(db, run.id, "node.skipped", nr.node_id, {"reason": reason})


def _apply_cancel(db: Session, run: Run) -> None:
    for nr in db.query(NodeRun).filter(NodeRun.run_id == run.id, NodeRun.status.in_(["pending", "awaiting_approval"])).all():
        cancel_node(db, run, nr)
    for a in db.query(Approval).filter(Approval.run_id == run.id, Approval.status == "pending").all():
        a.status, a.decided_at = "cancelled", utcnow()
        db.commit()
        emit(db, run.id, "approval.cancelled", a.node_id, {"approval_id": a.id})


def _finalize(db: Session, run: Run, definition: dict) -> None:
    rows = db.query(NodeRun).filter(NodeRun.run_id == run.id).all()
    statuses = [n.status for n in rows]
    if "running" in statuses:
        return
    if "awaiting_approval" in statuses and not run.cancel_requested:
        run.status = "awaiting_approval"
        db.commit()
        emit(db, run.id, "run.awaiting_approval")
        return
    for n in rows:  # pending with nothing left that can run: skip rather than hang
        if n.status == "pending":
            _skip(db, run, n, "Skipped because it could not be scheduled.")
    crit = {n["id"]: (n.get("params") or {}).get("criticality", "required") for n in definition["nodes"]}
    rows = db.query(NodeRun).filter(NodeRun.run_id == run.id).all()
    required_bad = [n for n in rows if n.status in ("failed", "skipped", "rejected") and crit.get(n.node_id) != "optional"]
    if run.cancel_requested:
        run.status, run.error = "cancelled", "Cancelled by request."
    elif any(n.status == "rejected" for n in rows):
        run.status, run.error = "rejected", "A human approver rejected a required step."
    elif required_bad:
        run.status = "failed"
        first = next((n for n in required_bad if n.status == "failed"), required_bad[0])
        run.error = f"Node '{first.label or first.node_id}' {first.status}: {first.error}"
    elif any(n.status in ("failed", "skipped") for n in rows):
        run.status = "partial"
        run.error = "Completed with optional step(s) that did not succeed: " + ", ".join(
            n.label or n.node_id for n in rows if n.status in ("failed", "skipped"))
    else:
        run.status = "completed"
    run.finished_at = utcnow()
    db.commit()
    emit(db, run.id, f"run.{run.status}", data={"error": run.error} if run.error else {})
    audit.record(db, actor_type="system", actor_id="engine", action=f"run.{run.status}",
                 outcome="success" if run.status == "completed" else "failure", resource_type="run",
                 resource_id=run.id, run_id=run.id, detail={"error": run.error})


# ------------------------------------------------------------------ node execution
def _claim(db: Session, nr: NodeRun, from_status: str) -> bool:
    """Atomic state transition; the single point that prevents double execution."""
    res = db.execute(update(NodeRun).where(NodeRun.id == nr.id, NodeRun.status == from_status)
                     .values(status="running", attempts=NodeRun.attempts + 1, started_at=utcnow()))
    db.commit()
    db.refresh(nr)
    return res.rowcount == 1


def _run_node(db: Session, run: Run, nr: NodeRun, node: dict, outputs: dict, user: User, upstream: Optional[list] = None) -> None:
    spec = CATALOG[node["type"]]
    approval: Optional[Approval] = None
    resumed = nr.status == "awaiting_approval"
    if (nr.checkpoint or {}).get("pending") is not None or resumed:
        approval = _approval_for(db, run.id, nr)
        if resumed and (approval is None or approval.status == "pending"):
            return
        if approval is not None and approval.status == "rejected":
            rej = db.query(ApprovalDecision).filter(ApprovalDecision.approval_id == approval.id,
                                                    ApprovalDecision.decision == "reject").first()
            who = db.get(User, rej.approver_id).display_name if rej else "an approver"
            nr.status, nr.finished_at, nr.failure_class = "rejected", utcnow(), "approval_rejected"
            nr.error = f"Rejected by {who}" + (f": {rej.comment}" if rej and rej.comment else "")
            nr.summary = nr.error
            db.commit()
            emit(db, run.id, "node.rejected", nr.node_id, {"reason": nr.error})
            return
        if approval is not None and approval.status == "cancelled":
            return cancel_node(db, run, nr)
        if approval is not None and approval.status != "approved":
            approval = None
    if resumed:
        if not _claim(db, nr, "awaiting_approval"):
            return  # another resume already took it: this is what makes retries safe
        emit(db, run.id, "node.resumed", nr.node_id, {"approval_id": approval.id if approval else None})
    else:
        if not _claim(db, nr, "pending"):
            return
        emit(db, run.id, "node.started", nr.node_id, {"type": nr.node_type, "agent": nr.agent,
                                                      "resumed": bool(nr.checkpoint)})

    t0 = time.perf_counter()
    try:
        if spec.kind == "trigger":
            return complete_node(db, run, nr, dict(run.inputs), "Workflow started with the supplied inputs.", 0)
        if spec.kind == "agent":
            return run_agent_task(db, run, nr, node, outputs, user, approval, upstream_evidence=upstream or [])
        if approval is not None:
            params = dict(approval.params_snapshot)  # exactly what the approvers reviewed
        else:
            params = coerce_param_types(spec, resolve_params(node.get("params") or {}, run.inputs, outputs))
        nr.input = redact_secrets(params)
        db.commit()
        _run_legacy(db, run, nr, spec, params, user, approval, t0)
    except KeyError as exc:
        fail_node(db, run, nr, f"Could not resolve a parameter reference: {exc.args[0]}", "validation_error")
    except Exception as exc:
        # A side-effecting tool may or may not have taken effect; say so rather than guess.
        note = " Outcome unknown; verify in the target system before retrying." if spec.side_effect else ""
        fail_node(db, run, nr, f"Unexpected error: {exc}.{note}", "outcome_unknown" if note else "execution_failure")


def _run_legacy(db: Session, run: Run, nr: NodeRun, spec, params: dict, user: User,
                approval: Optional[Approval], t0: float) -> None:
    """Single-operation catalog nodes (policy search and the department tool nodes) run through the
    same operation pipeline as agent tasks, acting as the department coordinator."""
    from core.platform.operations import Cancelled
    if spec.kind == "rag":
        agent_id = params.get("agent", "finance")
        if agent_id not in ("hr", "finance", "it"):
            return fail_node(db, run, nr, f"Unknown agent '{agent_id}'.", "validation_error")
        nr.agent, tool_name, args = agent_id, "rag_retrieve_policy", {"query": params["query"]}
    else:
        agent_id, tool_name, args = spec.agent, spec.tool, params
    entry = agent_entry(db, run, agent_id)
    if entry is None:
        return fail_node(db, run, nr, f"Agent '{agent_id}' is not registered.", "policy_rejection")
    nr.agent_version, nr.delegation = entry["version"], [agent_id]
    tc = TaskCtx(db, run, nr, user, agent_id, entry["config"], agent_id, deadline=time.monotonic() + 300)
    try:
        out = execute_operation(tc, 0, tool_name, args, approval=approval)
    except Cancelled:
        return cancel_node(db, run, nr)
    nr.tool_calls = (nr.tool_calls or []) + [{"tool": tool_name, "success": out.status == "ok", "latency_ms": out.latency_ms,
                                              "error": out.error}]
    if out.policy:
        nr.policy = out.policy
    ms = int((time.perf_counter() - t0) * 1000)
    if out.status == "awaiting_approval":
        nr.status = "awaiting_approval"
        nr.checkpoint = {"pending": {"index": 0, "tool": tool_name, "approval_id": out.approval_id}}
        nr.summary = f"Waiting for human approval. {out.policy['reason']}"
        nr.latency_ms = ms
        db.commit()
        emit(db, run.id, "node.awaiting_approval", nr.node_id, {"approval_id": out.approval_id})
        return
    if out.status != "ok":
        return fail_node(db, run, nr, out.error or "Tool call failed.", out.failure_class or "execution_failure")
    nr.checkpoint = None
    if spec.kind == "rag":
        d = out.data
        summary = (f"Retrieved {d['retrieved_chunks']} passage(s); top score {d['top_score']:.2f}."
                   if not d.get("abstained") else "No grounded answer: retrieval abstained.")
    else:
        summary = f"{spec.label}: {out.policy['reason']}" + (f" Approved by {out.approved_by}." if out.approved_by else "")
    complete_node(db, run, nr, out.data, summary, ms)


# ------------------------------------------------------------------ restart recovery
def recover_interrupted_runs() -> int:
    """Reconcile after a restart; every rule errs on the side of never repeating a side effect.

    - A node left `running` whose write started but was never recorded -> failed, "outcome unknown".
    - A legacy single-tool node left `running` -> failed likewise (conservative: it cannot be proven safe).
    - A read-only node or an agent task whose operations are all recorded -> back to `pending`; agent
      tasks resume from their checkpoint and replay recorded results instead of re-sending.
    - A run parked on approval whose decision landed just before the crash -> driven again."""
    db = session_factory()()
    to_submit: list[str] = []
    try:
        for run in db.query(Run).filter(Run.status.in_(["queued", "running"])).all():
            for nr in db.query(NodeRun).filter(NodeRun.run_id == run.id, NodeRun.status == "running").all():
                spec = CATALOG.get(nr.node_type)
                started_write = db.query(ToolExecution).filter(
                    ToolExecution.run_id == run.id, ToolExecution.node_id == nr.node_id,
                    ToolExecution.status == "started", ToolExecution.effect != "read").count()
                if started_write or (spec and spec.kind == "tool"):
                    fail_node(db, run, nr, "Engine restarted while this step was executing. Outcome unknown; "
                                           "verify in the target system before retrying.", "outcome_unknown")
                else:
                    nr.status = "pending"
                    db.commit()
            audit.record(db, actor_type="system", actor_id="engine", action="run.recovered", outcome="success",
                         resource_type="run", resource_id=run.id, run_id=run.id)
            to_submit.append(run.id)
        for run in db.query(Run).filter(Run.status == "awaiting_approval").all():
            decided = db.query(Approval).filter(Approval.run_id == run.id,
                                                Approval.status.in_(["approved", "rejected", "cancelled"])).first()
            if decided is not None or run.cancel_requested:
                to_submit.append(run.id)
        db.commit()
    finally:
        db.close()   # release before driving: drivers open their own sessions
    for run_id in to_submit:
        submit(run_id)
    return len(to_submit)
