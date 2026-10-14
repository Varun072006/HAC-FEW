import json
import time
from typing import Iterator, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.api import schemas as s
from apps.api.serializers import approval_out, node_run_out, run_summary, sum_usage
from core.platform import approvals as approval_svc
from core.platform import engine
from core.platform.db import get_session
from core.platform.db import session_factory
from core.platform.models import Approval, NodeRun, Run, RunEvent, ToolExecution, User
from core.platform.redaction import view_for
from core.platform.security import permissions_for, require
from apps.api.serializers import can_pii

router = APIRouter(tags=["Runs & approvals"])
TERMINAL = {"completed", "partial", "failed", "rejected", "cancelled"}


def _visible_run(db: Session, run_id: str, user: User) -> Run:
    run = db.get(Run, run_id)
    # 404 (not 403) for runs the caller may not see, so IDs cannot be probed.
    if run is None or (run.started_by != user.id and "run:read_all" not in permissions_for(user.role)):
        raise HTTPException(404, "Run not found.")
    return run


@router.get("/runs", response_model=s.RunList)
def list_runs(status: Optional[str] = None, workflow_id: Optional[str] = None,
              limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
              db: Session = Depends(get_session), user: User = Depends(require("run:read"))):
    q = db.query(Run)
    if "run:read_all" not in permissions_for(user.role):
        q = q.filter(Run.started_by == user.id)
    if status:
        q = q.filter(Run.status == status)
    if workflow_id:
        q = q.filter(Run.workflow_id == workflow_id)
    total = q.count()
    rows = q.order_by(Run.created_at.desc()).offset(offset).limit(limit).all()
    return s.RunList(items=[run_summary(db, r) for r in rows], total=total)


@router.get("/runs/{run_id}", response_model=s.RunDetail)
def get_run(run_id: str, db: Session = Depends(get_session), user: User = Depends(require("run:read"))):
    run = _visible_run(db, run_id, user)
    nodes = {n.node_id: n for n in db.query(NodeRun).filter(NodeRun.run_id == run.id)}
    crit = {n["id"]: (n.get("params") or {}).get("criticality") for n in run.definition_snapshot["nodes"]}
    ordered = [node_run_out(nodes[n["id"]], user, crit.get(n["id"])) for n in run.definition_snapshot["nodes"] if n["id"] in nodes]
    calls = db.query(func.count(ToolExecution.id)).filter(ToolExecution.run_id == run.id).scalar() or 0
    approvals = db.query(Approval).filter(Approval.run_id == run.id).order_by(Approval.requested_at).all()
    return s.RunDetail(**run_summary(db, run).model_dump(), inputs=view_for(run.inputs, can_pii(user)),
                       definition=s.WorkflowDefinition(**run.definition_snapshot), node_runs=ordered,
                       approvals=[approval_out(db, a, user) for a in approvals], last_seq=run.next_seq - 1,
                       budget=run.budget or {}, usage=sum_usage([n.usage for n in nodes.values() if n.usage]),
                       tool_calls_used=calls, plan_id=run.plan_id, cancel_requested=bool(run.cancel_requested))


@router.get("/runs/{run_id}/events", response_model=s.RunEventsPage)
def run_events(run_id: str, after: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=500),
               db: Session = Depends(get_session), user: User = Depends(require("run:read"))):
    """Cursor-based event feed. Poll with `after=<next_after>` until `terminal` is true."""
    run = _visible_run(db, run_id, user)
    rows = db.query(RunEvent).filter(RunEvent.run_id == run.id, RunEvent.seq > after)\
        .order_by(RunEvent.seq.asc()).limit(limit).all()
    pii = can_pii(user)
    events = [s.RunEventOut(seq=e.seq, ts=e.ts, type=e.type, node_id=e.node_id, data=view_for(e.data, pii)) for e in rows]
    db.refresh(run)
    return s.RunEventsPage(events=events, next_after=events[-1].seq if events else after,
                           run_status=run.status, terminal=run.status in TERMINAL)


@router.post("/runs/{run_id}/cancel", response_model=s.RunSummary, status_code=202)
def cancel_run(run_id: str, db: Session = Depends(get_session), user: User = Depends(require("run:read"))):
    """Stop a run: no new work starts, running tasks stop at their next operation boundary, and parked
    approvals are withdrawn. Allowed for the run's owner or a role with run:cancel_any."""
    run = _visible_run(db, run_id, user)
    if run.started_by != user.id and "run:cancel_any" not in permissions_for(user.role):
        raise HTTPException(403, "Only the run's owner or a role with run:cancel_any may cancel it.")
    if not engine.request_cancel(db, run, user):
        raise HTTPException(409, f"The run is already {run.status}.")
    db.refresh(run)
    return run_summary(db, run)


def _sse(seq: int, event: str, payload: dict) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.get("/runs/{run_id}/stream")
def stream_run(run_id: str, after: int = Query(0, ge=0), last_event_id: Optional[int] = Header(default=None),
               db: Session = Depends(get_session), user: User = Depends(require("run:read"))):
    """Server-Sent Events over the persisted event log. Every event is read back from the database, so a
    reconnecting client resumes exactly (`after=` or the Last-Event-ID header) and nothing is simulated.
    The stream ends when the run is terminal and drained, or after ~5 minutes (clients reconnect)."""
    run = _visible_run(db, run_id, user)
    pii = can_pii(user)
    cursor = max(after, last_event_id or 0)
    db.commit()  # release this request's transaction before streaming (SQLite writers would otherwise wait)

    def gen() -> Iterator[str]:
        nonlocal cursor
        deadline = time.monotonic() + 300
        last_ping = time.monotonic()
        yield "retry: 1500\n\n"
        while time.monotonic() < deadline:
            sdb = session_factory()()
            try:
                rows = sdb.query(RunEvent).filter(RunEvent.run_id == run.id, RunEvent.seq > cursor)\
                    .order_by(RunEvent.seq.asc()).limit(200).all()
                status = sdb.query(Run.status).filter(Run.id == run.id).scalar()
                events = [(e.seq, {"seq": e.seq, "ts": e.ts.isoformat(), "type": e.type, "node_id": e.node_id,
                                   "data": view_for(e.data, pii)}) for e in rows]
                sdb.commit()
            finally:
                sdb.close()
            for seq, payload in events:
                cursor = seq
                yield _sse(seq, "run_event", payload)
            if not events and status in TERMINAL:
                yield _sse(cursor, "end", {"run_status": status})
                return
            if not events:
                time.sleep(0.4)
                if time.monotonic() - last_ping > 15:
                    last_ping = time.monotonic()
                    yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- approvals
@router.get("/approvals", response_model=s.ApprovalList)
def list_approvals(status: Optional[str] = Query(None, pattern="^(pending|approved|rejected|cancelled)$"),
                   db: Session = Depends(get_session), user: User = Depends(require("run:read"))):
    q = db.query(Approval)
    if "approval:decide" not in permissions_for(user.role):
        q = q.filter(Approval.requested_by == user.id)  # requesters see only their own
    if status:
        q = q.filter(Approval.status == status)
    rows = q.order_by(Approval.requested_at.desc()).limit(200).all()
    return s.ApprovalList(items=[approval_out(db, a, user) for a in rows])


@router.get("/approvals/{approval_id}", response_model=s.ApprovalOut)
def get_approval(approval_id: str, db: Session = Depends(get_session), user: User = Depends(require("run:read"))):
    a = db.get(Approval, approval_id)
    if a is None or (a.requested_by != user.id and "approval:decide" not in permissions_for(user.role)):
        raise HTTPException(404, "Approval not found.")
    return approval_out(db, a, user)


@router.post("/approvals/{approval_id}/decision", response_model=s.ApprovalOut)
def decide_approval(approval_id: str, body: s.ApprovalDecisionIn, db: Session = Depends(get_session),
                    user: User = Depends(require("approval:decide"))):
    try:
        result = approval_svc.decide(db, approval_id, user, body.decision, body.comment)
    except approval_svc.ApprovalError as exc:
        raise HTTPException(exc.status_code, exc.message)
    if result.transitioned:  # exactly one caller observes the transition and resumes the run
        engine.submit(result.approval.run_id)
    db.refresh(result.approval)
    return approval_out(db, result.approval, user)
