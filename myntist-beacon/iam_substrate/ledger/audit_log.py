"""
Append-only audit log with SHA-256 hash chain.

Table: iam_substrate_log
Each row is hashed: sha256(timestamp + identity_id + event_type + S_after + prev_hash)
No UPDATE or DELETE — INSERT only.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from iam_substrate.substrate_api.models import AuditLogEntry


GENESIS_HASH = "0" * 64


def _compute_hash(
    timestamp: str,
    identity_id: str,
    event_type: str,
    S_after: Optional[float],
    prev_hash: str,
) -> str:
    s_after_str = str(S_after) if S_after is not None else ""
    payload = f"{timestamp}{identity_id}{event_type}{s_after_str}{prev_hash}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _get_last_hash(db: Session) -> str:
    last = (
        db.query(AuditLogEntry)
        .order_by(AuditLogEntry.id.desc())
        .first()
    )
    return last.hash if last else GENESIS_HASH


def append_audit_entry(
    db: Session,
    identity_id: str,
    event_type: str,
    action: Optional[str] = None,
    S_before: Optional[float] = None,
    S_after: Optional[float] = None,
) -> AuditLogEntry:
    """
    Append a new audit entry. Returns the created entry.
    """
    prev_hash = _get_last_hash(db)
    ts = datetime.now(timezone.utc).isoformat()
    entry_hash = _compute_hash(ts, identity_id, event_type, S_after, prev_hash)

    entry = AuditLogEntry(
        timestamp=datetime.now(timezone.utc),
        identity_id=identity_id,
        event_type=event_type,
        S_before=S_before,
        S_after=S_after,
        action=action,
        hash=entry_hash,
        prev_hash=prev_hash,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
