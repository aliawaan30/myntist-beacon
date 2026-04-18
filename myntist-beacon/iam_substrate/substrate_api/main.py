"""
IAM Substrate API — FastAPI application entry point.

Endpoints:
  GET  /health               → { status, timestamp, version }
  GET  /metrics              → Prometheus plaintext
  GET  /telemetry/latest     → latest telemetry snapshot
  GET  /telemetry/historical → recent telemetry rows (window set by TELEMETRY_WINDOW_HOURS)
  POST /score                → trigger scoring run
  POST /events               → receive Keycloak webhook event (HMAC verified)
  POST /validate             → validate a substrate bundle

Phase 2 endpoints:
  GET  /telemetry/finance    → six financial telemetry fields
  GET  /telemetry/temporal   → tau, Q, Ttau, D, S*D, admitted
  GET  /policy/active        → currently active IAM policies
  POST /policy/evaluate      → evaluate policies against a field state
  GET  /policy/rules         → full policy definitions (hot-reloaded from YAML) [admin: X-Admin-Key]
  GET  /hsce/ready           → HSCE interface readiness checklist
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from sqlalchemy.orm import Session

from beacon_core.telemetry.survivability_engine import get_engine
from beacon_core.telemetry.financial_engine import FinancialEngine
from beacon_core.telemetry.telemetry_exporter import TelemetryExporter
from beacon_core.lambdas.generate_status.handler import handler as _status_handler
from beacon_core.signing.field_signing_keys import build as _build_signing_keys
from beacon_core.signing.ed25519_signer import verify as _ed25519_verify
from .database import get_db, init_db
from .models import AuditLogEntry, Identity, TelemetryRecord
from .policy_engine import evaluate as policy_evaluate, get_active_policies, reload_policies
from .scoring import apply_event_weight, score_from_inputs, ema_blend
from .telemetry_emitter import emit_telemetry
from ..ledger.audit_log import append_audit_entry
from ..webhooks.hmac_handler import require_valid_signature

VERSION = "2.0.0"
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# How many hours back the historical telemetry endpoint looks.
# Seed data older than this is effectively hidden (and pruned on startup).
# Default is 720 hours (30 days) to preserve audit-grade history across restarts.
TELEMETRY_WINDOW_HOURS: int = int(os.getenv("TELEMETRY_WINDOW_HOURS", "720"))

HSCE_ENDPOINT = os.getenv("HSCE_ENDPOINT", "")

# Admin API key — set via ADMIN_API_KEY environment variable.
# When unset the endpoint is effectively disabled (all requests are rejected).
_ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "")

# Prometheus metrics
REQUEST_COUNT = Counter("substrate_requests_total", "Total requests", ["method", "path"])
S_GAUGE = Gauge("substrate_survivability_score", "Current S value")

_fin_engine = FinancialEngine()
_exporter = TelemetryExporter()


def _require_admin_key(x_admin_key: Optional[str] = Header(default=None)) -> None:
    """
    FastAPI dependency that enforces admin authentication via the X-Admin-Key header.

    Returns normally when the header matches the configured ADMIN_API_KEY.
    Raises HTTP 401 when the header is absent entirely.
    Raises HTTP 403 when the header is present but the value is incorrect.
    """
    if x_admin_key is None:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Admin-Key header. This endpoint requires admin authentication.",
        )
    if not _ADMIN_API_KEY or x_admin_key != _ADMIN_API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid admin key. Access denied.",
        )


def _prime_q_buffer() -> None:
    """
    Pre-populate the FinancialEngine Q variance buffer from DB history so
    coherence_signal is stable across process restarts rather than always
    starting from an empty in-memory deque.
    """
    try:
        rows = _exporter.get_recent_field_telemetry(days=7)
        for row in reversed(rows):  # oldest → newest
            q = row.get("Q") or row.get("q")
            if q is not None:
                _fin_engine.update_q_buffer(float(q))
        logger.info("_prime_q_buffer: loaded %d Q values from history", len(rows))
    except Exception as exc:
        logger.warning("_prime_q_buffer: failed to load history: %s", exc)


def _purge_stale_telemetry(db_session: Session) -> None:
    """
    Delete telemetry rows that pre-date the live window so seed data no longer
    appears in the Metrics Matrix.  Only the `telemetry` table is affected;
    `field_telemetry` (used for Q-variance priming) is left intact.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(hours=TELEMETRY_WINDOW_HOURS)
        deleted = (
            db_session.query(TelemetryRecord)
            .filter(TelemetryRecord.recorded_at < cutoff)
            .delete(synchronize_session=False)
        )
        db_session.commit()
        logger.info("_purge_stale_telemetry: removed %d stale rows (cutoff=%s)", deleted, cutoff.isoformat())
    except Exception as exc:
        db_session.rollback()
        logger.warning("_purge_stale_telemetry: failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from .database import get_session_local
    _SessionFactory = get_session_local()
    _db = _SessionFactory()
    try:
        _purge_stale_telemetry(_db)
    finally:
        _db.close()
    _prime_q_buffer()
    from .role_decay import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="IAM Substrate API",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class StripApiPrefixMiddleware(BaseHTTPMiddleware):
    """Strip /api prefix forwarded by AWS ALB; no-op when called via Express proxy."""
    async def dispatch(self, request: Request, call_next):
        path = request.scope["path"]
        if path.startswith("/api/"):
            request.scope["path"] = path[4:]
        return await call_next(request)


app.add_middleware(StripApiPrefixMiddleware)


# ── Pydantic request/response models ────────────────────────────────────────

class EventPayload(BaseModel):
    identity_id: str
    event_type: str
    Q: float = 1.0
    nabla_phi: float = 0.0
    tau: float = 1.0
    metadata: Optional[Dict[str, Any]] = None


class ScoreRequest(BaseModel):
    identity_id: str
    Q: float = 1.0
    nabla_phi: float = 0.0
    tau: float = 1.0


class ValidateRequest(BaseModel):
    bundle: Dict[str, Any]


class PolicyEvaluateRequest(BaseModel):
    S: float = 1.0
    delta_S: float = 0.0
    Q: float = 1.0
    tau: float = 1.0
    nabla_phi: float = 0.0
    field_state: str = "stable"
    D: float = 0.0
    Ttau: float = 0.0
    event_type: str = "*"


# ── Phase 1 Endpoints ────────────────────────────────────────────────────────

@app.get("/health")
def health_check() -> Dict[str, Any]:
    REQUEST_COUNT.labels(method="GET", path="/health").inc()
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
    }


@app.get("/field/v1/status.json")
def field_status() -> Dict[str, Any]:
    """Live signed status payload — reads from the telemetry DB."""
    REQUEST_COUNT.labels(method="GET", path="/field/v1/status.json").inc()
    return _status_handler({}, {})


@app.get("/.well-known/field-signing-keys.json")
def field_signing_keys() -> Dict[str, Any]:
    """W3C Ed25519VerificationKey2020 document — no private material."""
    REQUEST_COUNT.labels(method="GET", path="/.well-known/field-signing-keys.json").inc()
    return _build_signing_keys()


class VerifyRequest(BaseModel):
    payload: Dict[str, Any]
    signature: str


@app.post("/field/v1/verify")
def field_verify(body: VerifyRequest) -> Dict[str, Any]:
    """
    Verify an Ed25519 signature against the beacon public key.
    POST { payload: <status.json object>, signature: "ed25519:..." }

    The canonical bytes are computed from the payload with both the `hash`
    and `signature` fields removed, matching the bytes signed at generation
    time. Callers may include or omit the `hash` field — either way the
    same canonical bytes are used.

    Returns { valid: true/false }
    """
    REQUEST_COUNT.labels(method="POST", path="/field/v1/verify").inc()
    import json as _json
    core = {k: v for k, v in body.payload.items() if k not in ("hash", "signature")}
    payload_bytes = _json.dumps(core, sort_keys=True).encode()
    valid = _ed25519_verify(payload_bytes, body.signature)
    return {"valid": valid}


@app.get("/metrics")
def metrics() -> Response:
    REQUEST_COUNT.labels(method="GET", path="/metrics").inc()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/telemetry/latest")
def telemetry_latest(db: Session = Depends(get_db)) -> Dict[str, Any]:
    REQUEST_COUNT.labels(method="GET", path="/telemetry/latest").inc()

    record = (
        db.query(TelemetryRecord)
        .order_by(TelemetryRecord.recorded_at.desc())
        .first()
    )

    if record:
        return {
            "identity_id": record.identity_id,
            "S": record.S,
            "delta_S": record.delta_S,
            "Q": record.Q,
            "tau": record.tau,
            "nabla_phi": record.nabla_phi,
            "field_state": record.field_state,
            "timestamp": record.recorded_at.isoformat() if record.recorded_at else None,
            "hash": record.hash,
        }

    engine = get_engine()
    result = engine.compute(1.0, 0.0, 1.0)
    return {
        "identity_id": "system",
        "S": result.S,
        "delta_S": result.delta_S,
        "Q": 1.0,
        "tau": 1.0,
        "nabla_phi": 0.0,
        "field_state": result.field_state,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hash": None,
    }


@app.get("/telemetry/historical")
def telemetry_historical(db: Session = Depends(get_db)) -> Dict[str, Any]:
    REQUEST_COUNT.labels(method="GET", path="/telemetry/historical").inc()
    cutoff = datetime.utcnow() - timedelta(hours=TELEMETRY_WINDOW_HOURS)
    records = (
        db.query(TelemetryRecord)
        .filter(TelemetryRecord.recorded_at >= cutoff)
        .order_by(TelemetryRecord.recorded_at.desc())
        .all()
    )
    return {
        "records": [
            {
                "id": r.id,
                "identity_id": r.identity_id,
                "S": r.S,
                "delta_S": r.delta_S,
                "Q": r.Q,
                "tau": r.tau,
                "nabla_phi": r.nabla_phi,
                "field_state": r.field_state,
                "mttr": r.mttr,
                "hash": r.hash,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
            }
            for r in records
        ]
    }


@app.post("/score")
def trigger_score(req: ScoreRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    REQUEST_COUNT.labels(method="POST", path="/score").inc()

    result = score_from_inputs(req.Q, req.nabla_phi, req.tau)

    identity = db.query(Identity).filter(Identity.id == req.identity_id).first()
    if not identity:
        identity = Identity(
            id=req.identity_id,
            S=result.S,
            Q=req.Q,
            tau=req.tau,
            nabla_phi=req.nabla_phi,
            delta_S=result.delta_S,
            field_state=result.field_state,
        )
        db.add(identity)
    else:
        old_S = identity.S
        identity.S = result.S
        identity.Q = req.Q
        identity.tau = req.tau
        identity.nabla_phi = req.nabla_phi
        identity.delta_S = result.S - old_S
        identity.field_state = result.field_state

    db.commit()

    emit_telemetry(
        db=db,
        identity_id=req.identity_id,
        S=result.S,
        delta_S=result.delta_S,
        Q=req.Q,
        tau=req.tau,
        nabla_phi=req.nabla_phi,
        field_state=result.field_state,
    )

    _exporter.insert_field_telemetry({
        "identity_id": req.identity_id,
        "S": result.S,
        "delta_S": result.delta_S,
        "Q": req.Q,
        "tau": req.tau,
        "nabla_phi": req.nabla_phi,
        "field_state": result.field_state,
    })

    S_GAUGE.set(result.S)

    return {
        "identity_id": req.identity_id,
        "S": result.S,
        "delta_S": result.delta_S,
        "field_state": result.field_state,
    }


@app.post("/events", status_code=201)
async def receive_event(
    request: Request,
    db: Session = Depends(get_db),
    verified_body: bytes = Depends(require_valid_signature),
) -> Dict[str, Any]:
    REQUEST_COUNT.labels(method="POST", path="/events").inc()

    try:
        data = json.loads(verified_body)
        payload = EventPayload(**data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    identity = db.query(Identity).filter(Identity.id == payload.identity_id).first()
    current_S = identity.S if identity else 1.0

    # ── Phase 2: temporal policy gate ────────────────────────────────────────
    # Compute current field context for policy evaluation
    result_pre = score_from_inputs(payload.Q, payload.nabla_phi, payload.tau)
    _fin_engine.update_q_buffer(payload.Q)
    q_variance = _fin_engine.get_q_variance()
    D = _fin_engine.compute_liquidity_signal(
        delta_S=identity.delta_S if identity else 0.0,
        Q=payload.Q,
    )
    Ttau = _fin_engine.compute_coherence_signal(payload.tau, q_variance)

    policy_ctx: Dict[str, Any] = {
        "S": current_S,
        "delta_S": identity.delta_S if identity else 0.0,
        "Q": payload.Q,
        "tau": payload.tau,
        "nabla_phi": payload.nabla_phi,
        "field_state": result_pre.field_state,
        "D": D,
        "Ttau": Ttau,
    }
    policy_decision = policy_evaluate(policy_ctx, event_type=payload.event_type)

    # Persist temporal decision snapshot to iam_temporal_events
    _exporter.insert_iam_event({
        "identity_id": payload.identity_id,
        "event_type": payload.event_type,
        "S": current_S,
        "D": D,
        "Ttau": Ttau,
        "admitted": policy_decision["admitted"],
        "active_policies": json.dumps(policy_decision["active_policy_ids"]),
    })

    if not policy_decision["admitted"]:
        logger.warning(
            "POST /events: identity=%s blocked by policies %s",
            payload.identity_id,
            policy_decision["active_policy_ids"],
        )
        raise HTTPException(
            status_code=403,
            detail={
                "status": "blocked",
                "identity_id": payload.identity_id,
                "event_type": payload.event_type,
                "active_policy_ids": policy_decision["active_policy_ids"],
                "throttle_rate": policy_decision["throttle_rate"],
            },
        )
    # ── End policy gate ───────────────────────────────────────────────────────

    new_S = apply_event_weight(current_S, payload.event_type)
    result = score_from_inputs(payload.Q, payload.nabla_phi, payload.tau)
    blended_S = ema_blend(new_S, result.S)

    if not identity:
        identity = Identity(
            id=payload.identity_id,
            S=blended_S,
            Q=payload.Q,
            tau=payload.tau,
            nabla_phi=payload.nabla_phi,
            delta_S=blended_S - current_S,
            field_state=result.field_state,
        )
        db.add(identity)
    else:
        old_S = identity.S
        identity.S = blended_S
        identity.Q = payload.Q
        identity.tau = payload.tau
        identity.nabla_phi = payload.nabla_phi
        identity.delta_S = blended_S - old_S
        identity.field_state = result.field_state

    db.commit()

    append_audit_entry(
        db=db,
        identity_id=payload.identity_id,
        event_type=payload.event_type,
        action=f"event received: {payload.event_type}",
        S_before=current_S,
        S_after=blended_S,
    )

    emit_telemetry(
        db=db,
        identity_id=payload.identity_id,
        S=blended_S,
        delta_S=blended_S - current_S,
        Q=payload.Q,
        tau=payload.tau,
        nabla_phi=payload.nabla_phi,
        field_state=result.field_state,
    )

    _exporter.insert_field_telemetry({
        "identity_id": payload.identity_id,
        "S": blended_S,
        "delta_S": blended_S - current_S,
        "Q": payload.Q,
        "tau": payload.tau,
        "nabla_phi": payload.nabla_phi,
        "field_state": result.field_state,
        "liquidity_signal": D,
        "coherence_signal": Ttau,
    })

    S_GAUGE.set(blended_S)

    return {
        "status": "accepted",
        "identity_id": payload.identity_id,
        "event_type": payload.event_type,
        "S": blended_S,
        "field_state": result.field_state,
        "admitted": True,
        "active_policy_ids": policy_decision["active_policy_ids"],
        "throttle_rate": policy_decision["throttle_rate"],
    }


@app.post("/validate")
def validate_bundle(req: ValidateRequest) -> Dict[str, Any]:
    REQUEST_COUNT.labels(method="POST", path="/validate").inc()

    required_fields = {"identity_id", "S", "Q", "tau"}
    missing = required_fields - set(req.bundle.keys())

    if missing:
        return {"valid": False, "reason": f"Missing required fields: {', '.join(sorted(missing))}"}

    try:
        S = float(req.bundle["S"])
        Q = float(req.bundle["Q"])
        tau = float(req.bundle["tau"])
    except (ValueError, TypeError) as exc:
        return {"valid": False, "reason": f"Invalid numeric fields: {exc}"}

    if not (0.0 <= S <= 1.0):
        return {"valid": False, "reason": f"S must be in [0.0, 1.0], got {S}"}
    if Q <= 0:
        return {"valid": False, "reason": f"Q must be positive, got {Q}"}
    if not (0.0 <= tau <= 1.0):
        return {"valid": False, "reason": f"tau must be in [0.0, 1.0], got {tau}"}

    return {"valid": True, "bundle": req.bundle}


# ── Phase 2 Endpoints ────────────────────────────────────────────────────────

@app.get("/telemetry/finance")
def telemetry_finance(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return Phase 2 financial telemetry fields derived from latest snapshot."""
    REQUEST_COUNT.labels(method="GET", path="/telemetry/finance").inc()

    record = (
        db.query(TelemetryRecord)
        .order_by(TelemetryRecord.recorded_at.desc())
        .first()
    )

    if record:
        survival_out = {
            "S": record.S,
            "delta_S": record.delta_S,
            "Q": record.Q,
            "tau": record.tau,
            "nabla_phi": record.nabla_phi,
            "field_state": record.field_state,
        }
    else:
        engine = get_engine()
        result = engine.compute(1.0, 0.0, 1.0)
        survival_out = {
            "S": result.S,
            "delta_S": result.delta_S,
            "Q": 1.0,
            "tau": 1.0,
            "nabla_phi": 0.0,
            "field_state": result.field_state,
        }

    financial = _fin_engine.compute_all(survival_out, timescale_client=_exporter)

    return {
        "schema_version": financial["schema_version"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "float_yield": financial["float_yield"],
        "liquidity_signal": financial["liquidity_signal"],
        "coherence_signal": financial["coherence_signal"],
        "r_HSCE": financial["r_HSCE"],
        "float_reinvestment_rate": financial["float_reinvestment_rate"],
    }


@app.get("/telemetry/temporal")
def telemetry_temporal(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return temporal field state: tau, Q, Ttau, D (liquidity), S*D composite, admitted."""
    REQUEST_COUNT.labels(method="GET", path="/telemetry/temporal").inc()

    record = (
        db.query(TelemetryRecord)
        .order_by(TelemetryRecord.recorded_at.desc())
        .first()
    )

    if record:
        S = record.S
        Q = record.Q
        tau = record.tau
        delta_S = record.delta_S
        nabla_phi = record.nabla_phi
        field_state = record.field_state
    else:
        engine = get_engine()
        res = engine.compute(1.0, 0.0, 1.0)
        S = res.S
        Q = 1.0
        tau = 1.0
        delta_S = res.delta_S
        nabla_phi = 0.0
        field_state = res.field_state

    _fin_engine.update_q_buffer(Q)
    q_variance = _fin_engine.get_q_variance()
    D = _fin_engine.compute_liquidity_signal(delta_S, Q)
    Ttau = _fin_engine.compute_coherence_signal(tau, q_variance)

    ctx = {
        "S": S,
        "delta_S": delta_S,
        "Q": Q,
        "tau": tau,
        "nabla_phi": nabla_phi,
        "field_state": field_state,
        "D": D,
        "Ttau": Ttau,
    }
    policy_result = policy_evaluate(ctx, mutate_state=False)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "S": S,
        "Q": Q,
        "tau": tau,
        "D": D,
        "Ttau": Ttau,
        "S_times_D": S * D,
        "admitted": policy_result["admitted"],
        "active_policy_ids": policy_result["active_policy_ids"],
        "throttle_rate": policy_result["throttle_rate"],
    }


@app.get("/policy/active")
def policy_active() -> Dict[str, Any]:
    """Return the currently loaded temporal IAM policy definitions."""
    REQUEST_COUNT.labels(method="GET", path="/policy/active").inc()

    policies = get_active_policies()
    snapshot = _get_field_state_snapshot()
    evaluation = policy_evaluate(snapshot, mutate_state=False)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "policy_count": len(policies),
        "policies": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "action": p.get("action"),
                "throttle_rate": p.get("throttle_rate"),
                "enabled": p.get("enabled", True),
            }
            for p in policies
        ],
        "current_evaluation": evaluation,
    }


@app.post("/policy/evaluate")
def policy_evaluate_endpoint(req: PolicyEvaluateRequest) -> Dict[str, Any]:
    """Evaluate policies against a supplied field state."""
    REQUEST_COUNT.labels(method="POST", path="/policy/evaluate").inc()

    ctx = {
        "S": req.S,
        "delta_S": req.delta_S,
        "Q": req.Q,
        "tau": req.tau,
        "nabla_phi": req.nabla_phi,
        "field_state": req.field_state,
        "D": req.D,
        "Ttau": req.Ttau,
    }
    result = policy_evaluate(ctx, event_type=req.event_type, mutate_state=False)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "admitted": result["admitted"],
        "active_policy_ids": result["active_policy_ids"],
        "throttle_rate": result["throttle_rate"],
        "input": ctx,
    }


@app.get(
    "/policy/rules",
    summary="Full policy definitions (admin only)",
    description=(
        "Return the complete currently loaded policy definitions from temporal_policies.yaml, "
        "triggering a hot-reload if the file has changed since last load.\n\n"
        "**Authentication required:** supply a valid admin API key in the `X-Admin-Key` request "
        "header (configured via the `ADMIN_API_KEY` environment variable on the server).\n\n"
        "- Missing header → `401 Unauthorized`\n"
        "- Wrong key → `403 Forbidden`"
    ),
)
def policy_rules(_: None = Depends(_require_admin_key)) -> Dict[str, Any]:
    """Full policy definitions (admin only) — requires X-Admin-Key header."""
    REQUEST_COUNT.labels(method="GET", path="/policy/rules").inc()

    policies = get_active_policies()

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "policy_count": len(policies),
        "policies": policies,
    }


@app.get("/hsce/ready")
def hsce_ready() -> Dict[str, Any]:
    """Return HSCE interface readiness checklist."""
    REQUEST_COUNT.labels(method="GET", path="/hsce/ready").inc()

    endpoint_configured = bool(HSCE_ENDPOINT)
    exporter_ready = _exporter._initialized if hasattr(_exporter, "_initialized") else False

    checks = {
        "hsce_endpoint_configured": endpoint_configured,
        "field_schema_loaded": True,
        "telemetry_exporter_ready": exporter_ready,
        "interface_version": "v1",
    }
    ready = endpoint_configured and exporter_ready

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ready": ready,
        "checks": checks,
    }


def _get_field_state_snapshot() -> Dict[str, Any]:
    """Compute a current field state snapshot for policy evaluation."""
    engine = get_engine()
    result = engine.compute(1.0, 0.0, 1.0)
    _fin_engine.update_q_buffer(1.0)
    q_variance = _fin_engine.get_q_variance()
    D = _fin_engine.compute_liquidity_signal(result.delta_S, 1.0)
    Ttau = _fin_engine.compute_coherence_signal(1.0, q_variance)
    return {
        "S": result.S,
        "delta_S": result.delta_S,
        "Q": 1.0,
        "tau": 1.0,
        "nabla_phi": 0.0,
        "field_state": result.field_state,
        "D": D,
        "Ttau": Ttau,
    }
