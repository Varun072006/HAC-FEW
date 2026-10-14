"""Persisted node state transitions (one place, so every path emits the same events)."""
from typing import Optional

from sqlalchemy.orm import Session

from core.platform.events import emit
from core.platform.models import NodeRun, Run, utcnow
from core.platform.redaction import redact_secrets


def fail_node(db: Session, run: Run, nr: NodeRun, error: str, failure_class: str = "execution_failure",
              summary: Optional[str] = None) -> None:
    nr.status, nr.error, nr.finished_at, nr.failure_class = "failed", error, utcnow(), failure_class
    nr.summary = summary or error
    db.commit()
    emit(db, run.id, "node.failed", nr.node_id, {"error": error, "failure_class": failure_class})


def complete_node(db: Session, run: Run, nr: NodeRun, output: dict, summary: str, latency_ms: int) -> None:
    nr.status, nr.output, nr.summary, nr.finished_at = "completed", redact_secrets(output), summary, utcnow()
    nr.latency_ms = (nr.latency_ms or 0) + latency_ms
    db.commit()
    emit(db, run.id, "node.completed", nr.node_id, {"latency_ms": nr.latency_ms, "summary": summary})


def cancel_node(db: Session, run: Run, nr: NodeRun, reason: str = "Run cancelled.") -> None:
    nr.status, nr.error, nr.summary, nr.finished_at, nr.failure_class = "cancelled", reason, reason, utcnow(), "cancelled"
    db.commit()
    emit(db, run.id, "node.cancelled", nr.node_id, {"reason": reason})
