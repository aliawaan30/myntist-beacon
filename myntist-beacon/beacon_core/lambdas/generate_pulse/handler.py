"""
Lambda handler — generate_pulse

Derives pulse theme from S + delta_S. Sets TTL accordingly.
Phase 2: schema_version "2.0" with all 6 financial fields + validation.
  green  : S >= 0.85
  amber  : S >= 0.70
  red    : S <  0.70
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Dict

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
DATABASE_URL = os.getenv("DATABASE_URL", "")
ENABLE_FLOAT_ANALYTICS = os.getenv("ENABLE_FLOAT_ANALYTICS", "true").lower() == "true"

TTL_BY_THEME = {
    "green": 900,
    "amber": 300,
    "red": 60,
}


def _derive_theme(S: float, delta_S: float) -> str:
    if S >= 0.85:
        return "green"
    if S >= 0.70:
        return "amber"
    return "red"


def _write_to_s3(key: str, payload: Any) -> bool:
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
    Q = event.get("Q", 1.0)
    nabla_phi = event.get("nabla_phi", 0.0)
    tau = event.get("tau", 1.0)

    result = compute_survivability(Q, nabla_phi, tau)
    theme = _derive_theme(result.S, result.delta_S)
    ttl = TTL_BY_THEME[theme]

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
        "schema_version": "2.0",
        "generated_at": int(time.time()),
        "S": result.S,
        "delta_S": result.delta_S,
        "field_state": result.field_state,
        "theme": theme,
        "ttl_seconds": ttl,
        "status_url": f"{CLOUDFRONT_DOMAIN}/api/field/v1/status.json",
        "float_yield": financial.get("float_yield"),
        "liquidity_signal": financial.get("liquidity_signal"),
        "coherence_signal": financial.get("coherence_signal"),
        "r_HSCE": financial.get("r_HSCE"),
        "float_reinvestment_rate": financial.get("float_reinvestment_rate"),
    }

    if ENABLE_FLOAT_ANALYTICS:
        ok, errors = fin_validate(payload)
        if not ok:
            logger.error(
                "generate_pulse: financial validation failed: %s — aborting S3 write",
                errors,
            )
            return payload

    core_bytes = json.dumps(
        {k: v for k, v in payload.items() if k not in ("hash", "signature")},
        sort_keys=True,
    ).encode()
    sig = sign_bytes(core_bytes)
    if sig is not None:
        payload["signature"] = sig
    _write_to_s3("api/field/v1/pulse.json", payload)
    return payload
