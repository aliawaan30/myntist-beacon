"""
Role decay scheduler — runs every 60 seconds.

For any identity where S < 0.7: flags for remediation and calls autoheal.

Also runs a live telemetry emitter every 12 seconds so the dashboard always
has fresh, up-to-date records regardless of external event traffic.

Environment variables:
  TELEMETRY_BATCH_LIMIT      — max identities processed per live-telemetry
                               cycle (default: 50)
  TELEMETRY_RETENTION_HOURS  — delete telemetry rows older than this many
                               hours (default: 24); set to 0 to disable pruning
"""
from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import List

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler()
_scheduler_started = False


def check_and_heal() -> None:
    """Scheduled job: scan all identities and autoheal those with S < 0.7."""
    from .autoheal import run_autoheal
    from .database import get_session_local
    from .models import Identity

    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        identities = db.query(Identity).all()
        flagged = [
            {"id": identity.id, "S": identity.S, "field_state": identity.field_state}
            for identity in identities
            if identity.S < 0.7
        ]
        if flagged:
            logger.info("Role decay: %d identities flagged for autoheal", len(flagged))
            run_autoheal(flagged, db=db)
        else:
            logger.debug("Role decay check: all identities healthy")
    except Exception as exc:
        logger.error("Role decay check failed: %s", exc)
    finally:
        db.close()


def _int_env(name: str, default: int, min_val: int | None = None) -> int:
    """Read an integer environment variable, falling back to *default*.

    If *min_val* is given the returned value is clamped to at least that
    bound.  A warning is logged whenever the raw env value is invalid or
    below the minimum.
    """
    raw = os.environ.get(name, "")
    value = default
    if raw:
        try:
            parsed = int(raw)
            if min_val is not None and parsed < min_val:
                logger.warning(
                    "%s=%r is below minimum %d; using %d instead",
                    name, raw, min_val, min_val,
                )
                parsed = min_val
            value = parsed
        except (ValueError, TypeError):
            logger.warning(
                "%s=%r is not a valid integer; using default %d",
                name, raw, default,
            )
    return value


_TELEMETRY_BATCH_LIMIT: int = _int_env("TELEMETRY_BATCH_LIMIT", 50, min_val=1)
_TELEMETRY_RETENTION_HOURS: int = _int_env("TELEMETRY_RETENTION_HOURS", 24)

_telemetry_cursor = 0  # round-robin offset; advances each cycle


def emit_live_telemetry() -> None:
    """
    Scheduled job: emit a fresh telemetry record every 12 seconds so the
    dashboard always shows current timestamps even when no external events
    are arriving.

    Round-robin pagination ensures every registered identity receives a
    heartbeat over successive cycles, even when the total identity count
    exceeds _TELEMETRY_BATCH_LIMIT.

    Ordering is stable (created_at ASC, id ASC) so the offset is consistent
    across calls. The cursor advances by _TELEMETRY_BATCH_LIMIT each cycle
    and resets to 0 once the end of the set is reached.

    Falls back to a single 'system' record when no identities exist yet.
    """
    global _telemetry_cursor

    from .database import get_session_local
    from .models import Identity
    from .scoring import score_from_inputs
    from .telemetry_emitter import emit_telemetry

    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        total = db.query(Identity).count()

        if total == 0:
            # No identities registered yet — emit a system heartbeat so the
            # dashboard always has something to display.
            _telemetry_cursor = 0
            Q = max(0.01, min(2.0, 1.0 + random.gauss(0, 0.02)))
            tau = max(0.01, min(1.0, 1.0 + random.gauss(0, 0.005)))
            nabla_phi = max(0.0, min(0.5, 0.0 + random.gauss(0, 0.002)))
            result = score_from_inputs(Q, nabla_phi, tau)
            emit_telemetry(
                db=db,
                identity_id="system",
                S=result.S,
                delta_S=result.delta_S,
                Q=Q,
                tau=tau,
                nabla_phi=nabla_phi,
                field_state=result.field_state,
            )
            logger.debug("Live telemetry emitted: identity=system (no identities registered)")
            return

        # Ensure cursor is within bounds after any external identity deletions.
        _telemetry_cursor = _telemetry_cursor % total

        identities = (
            db.query(Identity)
            .order_by(Identity.created_at.asc(), Identity.id.asc())
            .offset(_telemetry_cursor)
            .limit(_TELEMETRY_BATCH_LIMIT)
            .all()
        )

        for identity in identities:
            base_Q = float(identity.Q or 1.0)
            base_tau = float(identity.tau or 1.0)
            base_nabla_phi = float(identity.nabla_phi or 0.0)

            Q = max(0.01, min(2.0, base_Q + random.gauss(0, 0.02)))
            tau = max(0.01, min(1.0, base_tau + random.gauss(0, 0.005)))
            nabla_phi = max(0.0, min(0.5, base_nabla_phi + random.gauss(0, 0.002)))

            result = score_from_inputs(Q, nabla_phi, tau)
            old_S = float(identity.S or result.S)
            delta_S = result.S - old_S

            emit_telemetry(
                db=db,
                identity_id=identity.id,
                S=result.S,
                delta_S=delta_S,
                Q=Q,
                tau=tau,
                nabla_phi=nabla_phi,
                field_state=result.field_state,
            )
            logger.debug(
                "Live telemetry emitted: identity=%s S=%.4f field_state=%s",
                identity.id, result.S, result.field_state,
            )

        # Advance cursor with modulo wrapping so we never land on an empty offset.
        _telemetry_cursor = (_telemetry_cursor + len(identities)) % total

        logger.info(
            "Live telemetry cycle complete: %d/%d identities updated, next cursor=%d",
            len(identities), total, _telemetry_cursor,
        )
    except Exception as exc:
        logger.error("emit_live_telemetry failed: %s", exc)
    finally:
        db.close()


def prune_telemetry() -> None:
    """
    Scheduled job: delete telemetry rows older than _TELEMETRY_RETENTION_HOURS.

    Runs every 60 seconds alongside the role-decay check.  The retention
    window is read once at startup from the TELEMETRY_RETENTION_HOURS env var
    (default 24 h).  Set the var to 0 to disable pruning entirely.
    """
    if _TELEMETRY_RETENTION_HOURS <= 0:
        return

    from .database import get_session_local
    from .models import TelemetryRecord

    cutoff = datetime.now(timezone.utc) - timedelta(hours=_TELEMETRY_RETENTION_HOURS)
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        deleted = (
            db.query(TelemetryRecord)
            .filter(TelemetryRecord.recorded_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        if deleted:
            logger.info(
                "Telemetry pruned: %d rows older than %d h removed",
                deleted,
                _TELEMETRY_RETENTION_HOURS,
            )
        else:
            logger.debug("Telemetry pruned: no rows older than %d h", _TELEMETRY_RETENTION_HOURS)
    except Exception as exc:
        logger.error("prune_telemetry failed: %s", exc)
        db.rollback()
    finally:
        db.close()


def start_scheduler() -> None:
    """Start the APScheduler background job."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler.add_job(check_and_heal, "interval", seconds=60, id="role_decay")
    _scheduler.add_job(emit_live_telemetry, "interval", seconds=12, id="live_telemetry")
    _scheduler.add_job(prune_telemetry, "interval", seconds=60, id="telemetry_pruner")
    _scheduler.start()
    _scheduler_started = True
    logger.info("Role decay scheduler started (60s interval)")
    logger.info("Live telemetry emitter started (12s interval)")
    logger.info(
        "Telemetry pruner started (60s interval, retention=%d h)",
        _TELEMETRY_RETENTION_HOURS,
    )


def stop_scheduler() -> None:
    """Stop the scheduler (call on app shutdown)."""
    global _scheduler_started
    if _scheduler_started:
        _scheduler.shutdown(wait=False)
        _scheduler_started = False


def get_flagged_identities(db) -> List[dict]:
    """Return identities with S < 0.7 without triggering autoheal."""
    from .models import Identity
    identities = db.query(Identity).all()
    return [
        {"id": i.id, "S": i.S, "field_state": i.field_state}
        for i in identities
        if i.S < 0.7
    ]
