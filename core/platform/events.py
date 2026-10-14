"""Numbered, redacted, persisted run events. The single writer of the run event feed."""
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from core.platform.models import Run, RunEvent, utcnow
from core.platform.redaction import redact_secrets


def emit(db: Session, run_id: str, type_: str, node_id: Optional[str] = None, data: Optional[dict] = None) -> int:
    """Append a numbered event. The counter is bumped atomically in the database, so concurrent
    task workers can never produce a duplicate or skipped sequence number."""
    db.execute(update(Run).where(Run.id == run_id).values(next_seq=Run.next_seq + 1))
    seq = db.query(Run.next_seq).filter(Run.id == run_id).scalar() - 1
    db.add(RunEvent(run_id=run_id, seq=seq, ts=utcnow(), type=type_, node_id=node_id,
                    data=redact_secrets(data or {})))
    db.commit()
    return seq
