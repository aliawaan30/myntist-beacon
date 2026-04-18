"""
Lambda handler — generate_status

Builds and signs the status.json payload. Writes to S3 (or /tmp stub).
Phase 2: schema_version "2.0" with all six financial fields.
Live data is read from the telemetry DB table when DATABASE_URL is set;
event parameters are only used as a fallback when no DB row exists.

DNS anchoring (when GODADDY_API_KEY is set):
  _s.v1         updated on every invocation with live survivability data
  _buoy.latest  updated with the canonical status.json URL and payload hash
  _float.audit  updated with real float analytics from FinancialEngine
  _ledger.anchor updated when IPFS_API_KEY + ZENODO_API_KEY are both configured
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from beacon_core.telemetry.survivability_engine import compute_survivability
from beacon_core.telemetry.financial_engine import FinancialEngine
from beacon_core.telemetry.financial_validator import validate as fin_validate
from beacon_core.telemetry.telemetry_exporter import TelemetryExporter
from beacon_core.signing.kms_signer import sign_bytes

logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
CLOUDFRONT_DOMAIN = os.getenv("CLOUDFRONT_DOMAIN", "https://myntist.com")
# CANONICAL_URL — full URL of the status.json endpoint.
# Set this to the current deployment URL so the payload always advertises
# the correct address regardless of the underlying host.
# Example: https://myntist.com/api/field/v1/status.json
CANONICAL_URL = os.getenv("CANONICAL_URL", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ENABLE_FLOAT_ANALYTICS = os.getenv("ENABLE_FLOAT_ANALYTICS", "true").lower() == "true"
ENABLE_DNS_UPDATE = os.getenv("ENABLE_DNS_UPDATE", "true").lower() == "true"
ENABLE_LEDGER_ANCHOR = os.getenv("ENABLE_LEDGER_ANCHOR", "true").lower() == "true"


def _fetch_live_telemetry() -> Optional[Dict[str, Any]]:
    """
    Pull the most recent row from the telemetry table.
    Returns a dict with Q, nabla_phi, tau, S, delta_S, field_state,
    or None if the DB is unavailable or the table is empty.
    """
    if not DATABASE_URL:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT "S", "delta_S", "Q", tau, nabla_phi, field_state
            FROM telemetry
            ORDER BY recorded_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        S, delta_S, Q, tau, nabla_phi, field_state = row
        return {
            "S": float(S),
            "delta_S": float(delta_S),
            "Q": float(Q),
            "tau": float(tau),
            "nabla_phi": float(nabla_phi),
            "field_state": field_state,
        }
    except Exception as exc:
        logger.warning("Could not fetch live telemetry from DB: %s", exc)
        return None


def _write_to_s3(key: str, payload: Dict[str, Any]) -> bool:
    if not S3_BUCKET:
        logger.warning("S3_BUCKET not set — writing to /tmp stub")
        local_path = f"/tmp/{key.replace('/', '_')}"
        with open(local_path, "w") as f:
            json.dump(payload, f, indent=2)
        return False
    try:
        import boto3
        client = boto3.client("s3", region_name=AWS_REGION)
        client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(payload, indent=2).encode(),
            ContentType="application/json",
        )
        logger.info("Written to s3://%s/%s", S3_BUCKET, key)
        return True
    except Exception as exc:
        logger.error("S3 write failed: %s", exc)
        return False


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda entry point."""
    ts = int(time.time())

    live = _fetch_live_telemetry()

    if live:
        logger.info("Using live telemetry from DB: S=%.4f Q=%.4f field_state=%s",
                    live["S"], live["Q"], live["field_state"])
        Q = live["Q"]
        nabla_phi = live["nabla_phi"]
        tau = live["tau"]
        survival_out = live
    else:
        logger.warning("No live DB data — falling back to event parameters")
        Q = event.get("Q", 1.0)
        nabla_phi = event.get("nabla_phi", 0.0)
        tau = event.get("tau", 1.0)
        result = compute_survivability(Q, nabla_phi, tau)
        survival_out = {
            "S": result.S,
            "delta_S": result.delta_S,
            "Q": Q,
            "tau": tau,
            "nabla_phi": nabla_phi,
            "field_state": result.field_state,
        }

    fin_engine = FinancialEngine()
    timescale_client = TelemetryExporter(DATABASE_URL) if DATABASE_URL else None
    financial = fin_engine.compute_all(survival_out, timescale_client=timescale_client)

    payload: Dict[str, Any] = {
        "schema_version": financial["schema_version"],
        "generated_at": ts,
        "S": survival_out["S"],
        "delta_S": survival_out["delta_S"],
        "Q": Q,
        "tau": tau,
        "nabla_phi": nabla_phi,
        "field_state": survival_out["field_state"],
        "feeds_fresh": live is not None,
        "url": CANONICAL_URL if CANONICAL_URL else f"{CLOUDFRONT_DOMAIN}/api/field/v1/status.json",
        "float_yield": financial["float_yield"],
        "liquidity_signal": financial["liquidity_signal"],
        "coherence_signal": financial["coherence_signal"],
        "r_HSCE": financial["r_HSCE"],
        "float_reinvestment_rate": financial["float_reinvestment_rate"],
    }

    if ENABLE_FLOAT_ANALYTICS:
        ok, errors = fin_validate(payload)
        if not ok:
            logger.error(
                "generate_status: financial validation failed: %s",
                errors,
            )

    core_bytes = json.dumps(payload, sort_keys=True).encode()
    payload_hash = hashlib.sha256(core_bytes).hexdigest()
    sig = sign_bytes(core_bytes)
    payload["hash"] = payload_hash
    if sig is not None:
        payload["signature"] = sig

    _write_to_s3("api/field/v1/status.json", payload)

    if ENABLE_DNS_UPDATE:
        try:
            from beacon_core.dns.godaddy_updater import update_dns_records

            cid: Optional[str] = None
            doi: Optional[str] = None

            if ENABLE_LEDGER_ANCHOR:
                cid, doi = _anchor_to_ledger(payload)

            update_dns_records(
                S=survival_out["S"],
                delta_S=survival_out["delta_S"],
                tau=tau,
                Q=Q,
                payload_hash=payload_hash,
                cid=cid,
                doi=doi,
                float_yield=financial.get("float_yield"),
                float_reinvestment_rate=financial.get("float_reinvestment_rate"),
                coherence_signal=financial.get("coherence_signal"),
            )
        except Exception as exc:
            logger.warning("DNS update failed (non-fatal): %s", exc)

    return payload


def _anchor_to_ledger(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Pin the payload to IPFS and create a Zenodo deposit.

    Returns:
        (cid, doi) — either or both may be None if credentials are missing or
        the operation fails. Failure is non-fatal and logged as a warning.
    """
    cid: Optional[str] = None
    doi: Optional[str] = None

    try:
        from identity_loop.zenodo.ipfs_pinner import pin_json
        result = pin_json(
            payload,
            name=f"myntist-beacon-{payload.get('generated_at', 'unknown')}",
        )
        if result.get("status") == "pinned":
            cid = result.get("cid")
            logger.info("IPFS anchor: cid=%s", cid)
        elif result.get("status") == "stub":
            logger.info("IPFS anchor skipped — credentials not configured")
        else:
            logger.warning("IPFS anchor failed: %s", result)
    except Exception as exc:
        logger.warning("IPFS pin error: %s", exc)

    try:
        from identity_loop.zenodo.zenodo_client import deposit
        S_val = payload.get("S", 0.0)
        fs = payload.get("field_state", "unknown")
        result = deposit(
            title=f"Myntist Beacon Status — ts={payload.get('generated_at', 'unknown')}",
            description=(
                f"Sovereign beacon status.json snapshot. "
                f"S={S_val:.4f}, field_state={fs}."
            ),
            file_content=json.dumps(payload, indent=2).encode(),
            file_name=f"status-{payload.get('generated_at', 'unknown')}.json",
        )
        if result.get("status") == "published":
            doi = result.get("doi")
            logger.info("Zenodo anchor: doi=%s", doi)
        elif result.get("status") == "stub":
            logger.info("Zenodo anchor skipped — credentials not configured")
        else:
            logger.warning("Zenodo deposit failed: %s", result)
    except Exception as exc:
        logger.warning("Zenodo deposit error: %s", exc)

    return cid, doi
