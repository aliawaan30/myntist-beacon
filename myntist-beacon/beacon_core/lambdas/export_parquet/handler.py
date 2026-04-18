"""
Lambda handler — export_parquet

Weekly job: queries last 7 days of field_telemetry, exports to Parquet
with snappy compression, writes to S3 (or /tmp stub).
Skips entirely when PARQUET_EXPORT_ENABLED=false.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from beacon_core.telemetry.telemetry_exporter import TelemetryExporter

logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DATABASE_URL = os.getenv("DATABASE_URL", "")
PARQUET_EXPORT_ENABLED = os.getenv("PARQUET_EXPORT_ENABLED", "true").lower() == "true"


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
            logger.info("Parquet written to %s", dest)
            return dest
        except Exception as exc:
            logger.error("S3 write failed: %s — falling back to /tmp", exc)

    local_path = f"/tmp/{key.replace('/', '_')}"
    with open(local_path, "wb") as f:
        f.write(body)
    logger.warning("S3_BUCKET not set — Parquet written to %s", local_path)
    return local_path


def _records_to_parquet(records: list) -> bytes:
    """Convert records list to Parquet bytes using pyarrow + snappy."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        from io import BytesIO

        if not records:
            schema = pa.schema([
                pa.field("time", pa.string()),
                pa.field("S", pa.float64()),
                pa.field("float_yield", pa.float64()),
            ])
            table = pa.table({}, schema=schema)
        else:
            str_keys = ["time", "identity_id", "field_state", "schema_version"]
            float_keys = [
                "S", "delta_S", "Q", "tau", "nabla_phi",
                "float_yield", "liquidity_signal", "coherence_signal",
                "r_HSCE", "float_reinvestment_rate",
            ]

            columns: Dict[str, list] = {k: [] for k in str_keys + float_keys}
            for r in records:
                for k in str_keys:
                    val = r.get(k)
                    columns[k].append(str(val) if val is not None else None)
                for k in float_keys:
                    val = r.get(k)
                    columns[k].append(float(val) if val is not None else None)

            table = pa.table(columns)

        buf = BytesIO()
        pq.write_table(table, buf, compression="snappy")
        return buf.getvalue()

    except ImportError:
        logger.warning("pyarrow not installed — writing JSON stub instead of Parquet")
        return json.dumps([
            {k: str(v) if hasattr(v, "isoformat") else v for k, v in r.items()}
            for r in records
        ], indent=2).encode()


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Weekly lambda entry point."""
    if not PARQUET_EXPORT_ENABLED:
        logger.info("PARQUET_EXPORT_ENABLED=false — skipping export")
        return {"status": "skipped", "reason": "PARQUET_EXPORT_ENABLED=false"}

    exporter = TelemetryExporter(DATABASE_URL)
    records = exporter.get_recent_field_telemetry(days=7)

    ts = int(time.time())
    week_label = datetime.now(timezone.utc).strftime("%Y-W%W")

    parquet_bytes = _records_to_parquet(records)
    dest = _write_to_s3_or_tmp(
        f"parquet/field_telemetry/{week_label}/telemetry.parquet",
        parquet_bytes,
        "application/octet-stream",
    )

    result = {
        "schema_version": "2.0",
        "generated_at": ts,
        "week": week_label,
        "period_days": 7,
        "record_count": len(records),
        "parquet_location": dest,
    }
    logger.info("Parquet export complete: %d records, week=%s", len(records), week_label)
    return result
