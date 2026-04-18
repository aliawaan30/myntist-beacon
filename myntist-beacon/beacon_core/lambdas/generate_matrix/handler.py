"""
Lambda handler — generate_matrix

Builds a 7-day rolling telemetry matrix.
Phase 2: schema_version "2.0" with all 6 financial fields + validation.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from beacon_core.telemetry.financial_engine import FinancialEngine
from beacon_core.telemetry.financial_validator import validate as fin_validate
from beacon_core.telemetry.telemetry_exporter import TelemetryExporter
from beacon_core.signing.kms_signer import sign_bytes

logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ENABLE_FLOAT_ANALYTICS = os.getenv("ENABLE_FLOAT_ANALYTICS", "true").lower() == "true"


def _fetch_telemetry_7days() -> List[Dict[str, Any]]:
    """Pull last 7 days of telemetry from DB, or return stub data."""
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set — returning stub matrix data")
        return _stub_matrix()
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from iam_substrate.substrate_api.models import TelemetryRecord

        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        Session = sessionmaker(bind=engine)
        db = Session()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        records = (
            db.query(TelemetryRecord)
            .filter(TelemetryRecord.recorded_at >= cutoff)
            .order_by(TelemetryRecord.recorded_at.desc())
            .limit(100)
            .all()
        )
        db.close()
        return [
            {
                "timestamp": r.recorded_at.isoformat() if r.recorded_at else None,
                "S": r.S,
                "delta_S": r.delta_S,
                "Q": r.Q,
                "tau": r.tau,
                "nabla_phi": r.nabla_phi,
                "field_state": r.field_state,
            }
            for r in records
        ]
    except Exception as exc:
        logger.error("Matrix DB fetch failed: %s — using stub", exc)
        return _stub_matrix()


def _stub_matrix() -> List[Dict[str, Any]]:
    now = time.time()
    return [
        {
            "timestamp": datetime.fromtimestamp(now - i * 3600, tz=timezone.utc).isoformat(),
            "S": round(0.85 - i * 0.02, 4),
            "delta_S": round(-0.02, 4),
            "Q": 1.0,
            "tau": 1.0,
            "nabla_phi": 0.0,
            "field_state": "stable" if i < 3 else "excitation",
        }
        for i in range(7)
    ]


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
    """Lambda entry point."""
    matrix = _fetch_telemetry_7days()

    fin_engine = FinancialEngine()
    financial: Dict[str, Any] = {}
    if matrix:
        last = matrix[0]
        timescale_client = TelemetryExporter(DATABASE_URL) if DATABASE_URL else None
        financial = fin_engine.compute_all(last, timescale_client=timescale_client)

    payload: Dict[str, Any] = {
        "schema_version": "2.0",
        "generated_at": int(time.time()),
        "window_days": 7,
        "records": matrix,
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
                "generate_matrix: financial validation failed: %s — aborting S3 write",
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
    _write_to_s3("api/field/v1/matrix.json", payload)
    return payload
