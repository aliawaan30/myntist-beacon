"""
Lambda handler — generate_benchmarks

Returns operational + financial benchmarks.
Phase 2: schema_version "2.0" with all 6 live financial fields + validation.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Dict

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

BENCHMARKS = {
    "operational_target": {
        "S_min": 0.85,
        "S_ideal": 0.95,
        "Q_max": 1.2,
        "tau_min": 0.80,
        "mttr_max_minutes": 15,
    },
    "tested_ceiling": {
        "S_max": 1.0,
        "Q_min": 0.1,
        "tau_max": 1.0,
        "mttr_min_minutes": 0,
    },
}

FINANCIAL_BENCHMARKS = {
    "float_yield_target": 0.007,
    "float_yield_min": 0.0,
    "liquidity_signal_min": 0.10,
    "r_HSCE_band_low": 0.005,
    "r_HSCE_band_high": 0.03,
    "Ttau_alert_threshold": 0.25,
    "float_reinvestment_rate_default": 0.63,
}


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
    # Compute live financial metrics using benchmark operational target values
    fin_engine = FinancialEngine()
    benchmark_input = {
        "S": BENCHMARKS["operational_target"]["S_ideal"],
        "delta_S": 0.0,
        "Q": BENCHMARKS["operational_target"]["Q_max"],
        "tau": BENCHMARKS["operational_target"]["tau_min"],
        "nabla_phi": 0.0,
        "field_state": "stable",
    }
    timescale_client = TelemetryExporter(DATABASE_URL) if DATABASE_URL else None
    financial = fin_engine.compute_all(benchmark_input, timescale_client=timescale_client)

    payload: Dict[str, Any] = {
        "schema_version": "2.0",
        "generated_at": int(time.time()),
        "benchmarks": BENCHMARKS,
        "financial_benchmarks": FINANCIAL_BENCHMARKS,
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
                "generate_benchmarks: financial validation failed: %s — aborting S3 write",
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
    _write_to_s3("api/field/v1/benchmarks.json", payload)
    return payload
