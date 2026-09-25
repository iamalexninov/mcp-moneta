"""Tamper-evident audit log.

Each row stores ``hash = SHA256(prev_hash || canonical_json(row))``. Editing
or deleting any row breaks the chain, which ``verify_chain`` detects (the
admin panel shows the result). Secrets and full payloads are never logged,
only identifiers and counts.
"""

import hashlib
import json
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, utcnow

GENESIS = "0" * 64
_lock = threading.Lock()


def _digest(prev_hash: str, row: dict) -> str:
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + canonical).encode()).hexdigest()


def _row_dict(e: AuditLog) -> dict:
    return {
        "ts": e.ts.isoformat(),
        "tenant_id": e.tenant_id,
        "user_id": e.user_id,
        "client_id": e.client_id,
        "action": e.action,
        "outcome": e.outcome,
        "ip": e.ip,
        "request_id": e.request_id,
        "detail": e.detail,
    }


def record(
    db: Session,
    action: str,
    outcome: str = "success",
    *,
    tenant_id: int | None = None,
    user_id: int | None = None,
    client_id: str | None = None,
    ip: str | None = None,
    request_id: str | None = None,
    **detail,
) -> None:
    with _lock:  # serialise chain within the process; SQL Server: use SERIALIZABLE or a sequence
        last = db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar()
        entry = AuditLog(
            ts=utcnow().replace(microsecond=0),
            tenant_id=tenant_id,
            user_id=user_id,
            client_id=client_id,
            action=action,
            outcome=outcome,
            ip=ip,
            request_id=request_id,
            detail=json.dumps(detail, sort_keys=True, default=str),
            prev_hash=last or GENESIS,
        )
        entry.hash = _digest(entry.prev_hash, _row_dict(entry))
        db.add(entry)
        db.flush()


def verify_chain(db: Session) -> tuple[bool, int | None]:
    """Returns (ok, id_of_first_broken_row)."""
    prev = GENESIS
    for e in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        if e.prev_hash != prev or _digest(prev, _row_dict(e)) != e.hash:
            return False, e.id
        prev = e.hash
    return True, None
