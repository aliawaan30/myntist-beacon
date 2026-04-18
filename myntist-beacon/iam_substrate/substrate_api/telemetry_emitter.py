"""
Telemetry emitter — stores telemetry records to the database.
Phase 2: adds liquidity_signal, coherence_signal, admitted, active_policies fields.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from .models import TelemetryRecord


def emit_telemetry(
    db: Session,
    identity_id: str,
    S: float,
    delta_S: float,
    Q: float,
    tau: float,
    nabla_phi: float,
    field_state: str,
    mttr: Optional[float] = None,
    liquidity_signal: Optional[float] = None,
    coherence_signal: Optional[float] = None,
    admitted: Optional[bool] = None,
    active_policies: Optional[List[str]] = None,
) -> TelemetryRecord:
    """Persist a telemetry snapshot to the database and return it."""
    ts = datetime.now(timezone.utc).isoformat()
    payload_hash = hashlib.sha256(
        f"{ts}{identity_id}{S}{Q}{tau}{nabla_phi}".encode()
    ).hexdigest()

    record = TelemetryRecord(
        identity_id=identity_id,
        S=S,
        delta_S=delta_S,
        Q=Q,
        tau=tau,
        nabla_phi=nabla_phi,
        field_state=field_state,
        mttr=mttr,
        hash=payload_hash,
        liquidity_signal=liquidity_signal,
        coherence_signal=coherence_signal,
        admitted=admitted,
        active_policies=",".join(active_policies) if active_policies else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
