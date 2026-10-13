"""Tamper-evident audit trail: each event stores the SHA-256 of (prev_hash + canonical content).

Writes are serialised with a process-level lock. A multi-process deployment must serialise
chain appends in the database (e.g. a PostgreSQL advisory lock); this is a known gap."""
import hashlib
import json
import threading
from typing import Any, Optional
from sqlalchemy.orm import Session

from core.platform.models import AuditEvent, utcnow
from core.platform.redaction import redact_secrets

_chain_lock = threading.Lock()
GENESIS = "0" * 64


def _digest(prev_hash, ts, actor_type, actor_id, actor_role, action, resource_type,
            resource_id, run_id, outcome, risk, detail) -> str:
    body = json.dumps(
        [prev_hash, ts.isoformat(), actor_type, actor_id, actor_role, action, resource_type,
         resource_id, run_id, outcome, risk, detail],
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def record(db: Session, *, actor_type: str, actor_id: str, action: str, outcome: str,
           actor_role: Optional[str] = None, resource_type: Optional[str] = None,
           resource_id: Optional[str] = None, run_id: Optional[str] = None,
           risk: Optional[str] = None, detail: Optional[dict[str, Any]] = None) -> AuditEvent:
    """Append an audit event and commit it immediately (audit must survive caller rollbacks)."""
    detail = redact_secrets(detail or {})
    with _chain_lock:
        last = db.query(AuditEvent).order_by(AuditEvent.id.desc()).first()
        prev = last.hash if last else GENESIS
        ts = utcnow().replace(microsecond=0)
        h = _digest(prev, ts, actor_type, actor_id, actor_role, action, resource_type,
                    resource_id, run_id, outcome, risk, detail)
        ev = AuditEvent(ts=ts, actor_type=actor_type, actor_id=actor_id, actor_role=actor_role,
                        action=action, resource_type=resource_type, resource_id=resource_id,
                        run_id=run_id, outcome=outcome, risk=risk, detail=detail,
                        prev_hash=prev, hash=h)
        db.add(ev)
        db.commit()
        return ev


def verify_chain(db: Session) -> dict:
    prev = GENESIS
    count = 0
    for ev in db.query(AuditEvent).order_by(AuditEvent.id.asc()).yield_per(500):
        expected = _digest(prev, ev.ts, ev.actor_type, ev.actor_id, ev.actor_role, ev.action,
                           ev.resource_type, ev.resource_id, ev.run_id, ev.outcome, ev.risk, ev.detail)
        if ev.prev_hash != prev or ev.hash != expected:
            return {"valid": False, "checked": count, "first_invalid_id": ev.id}
        prev = ev.hash
        count += 1
    return {"valid": True, "checked": count, "first_invalid_id": None}
