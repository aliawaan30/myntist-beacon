"""
Lambda handler — generate_float_ledger

Monthly job: queries last 30 days of field_telemetry, computes float aggregates,
writes CSV + JSON summary to S3 (or /tmp stub when S3_BUCKET is not set).
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from io import StringIO
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from beacon_core.telemetry.telemetry_exporter import TelemetryExporter

logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DATABASE_URL = os.getenv("DATABASE_URL", "")


def _write_to_s3_or_tmp(key: str, body: bytes, content_type: str) -> str:
    if S3_BUCKET:
        try:
            import boto3
            client = boto3.client("s3", region_name=AWS_REGION)
            client.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
            dest = f"s3://{S3_BUCKET}/{key}"
            logger.info("Float ledger written to %s", dest)
            return dest
        except Exception as exc:
            logger.error("S3 write failed: %s — falling back to /tmp", exc)

    local_path = f"/tmp/{key.replace('/', '_')}"
    with open(local_path, "wb") as f:
        f.write(body)
    logger.warning("S3_BUCKET not set — float ledger written to %s", local_path)
    return local_path


def _compute_aggregates(records: list) -> Dict[str, Any]:
    if not records:
        return {
            "count": 0,
            "avg_S": None,
            "avg_float_yield": None,
            "total_float_yield": None,
            "avg_liquidity_signal": None,
            "avg_r_HSCE": None,
            "avg_float_reinvestment_rate": None,
        }

    count = len(records)
    s_values = [r["S"] for r in records if r.get("S") is not None]
    fy_values = [r["float_yield"] for r in records if r.get("float_yield") is not None]
    ls_values = [r["liquidity_signal"] for r in records if r.get("liquidity_signal") is not None]
    rh_values = [r["r_HSCE"] for r in records if r.get("r_HSCE") is not None]
    fr_values = [r["float_reinvestment_rate"] for r in records if r.get("float_reinvestment_rate") is not None]

    def avg(lst):
        return sum(lst) / len(lst) if lst else None

    return {
        "count": count,
        "avg_S": avg(s_values),
        "avg_float_yield": avg(fy_values),
        "total_float_yield": sum(fy_values) if fy_values else None,
        "avg_liquidity_signal": avg(ls_values),
        "avg_r_HSCE": avg(rh_values),
        "avg_float_reinvestment_rate": avg(fr_values),
    }


def _build_csv(records: list) -> bytes:
    if not records:
        return b"no records\n"
    fieldnames = [
        "time", "identity_id", "S", "delta_S", "Q", "tau",
        "float_yield", "liquidity_signal", "coherence_signal",
        "r_HSCE", "float_reinvestment_rate", "schema_version",
    ]
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        row = {k: r.get(k) for k in fieldnames}
        if hasattr(row["time"], "isoformat"):
            row["time"] = row["time"].isoformat()
        writer.writerow(row)
    return buf.getvalue().encode()


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Monthly lambda entry point."""
    exporter = TelemetryExporter(DATABASE_URL)
    records = exporter.get_recent_field_telemetry(days=30)

    aggregates = _compute_aggregates(records)
    ts = int(time.time())
    month_label = datetime.now(timezone.utc).strftime("%Y-%m")

    csv_bytes = _build_csv(records)
    csv_dest = _write_to_s3_or_tmp(
        f"ledger/float/{month_label}/float_ledger.csv",
        csv_bytes,
        "text/csv",
    )

    summary = {
        "schema_version": "2.0",
        "generated_at": ts,
        "period_days": 30,
        "month": month_label,
        "aggregates": aggregates,
        "csv_location": csv_dest,
    }
    json_dest = _write_to_s3_or_tmp(
        f"ledger/float/{month_label}/float_summary.json",
        json.dumps(summary, indent=2).encode(),
        "application/json",
    )
    summary["json_location"] = json_dest

    logger.info("Float ledger complete: %d records, month=%s", len(records), month_label)
    return summary
