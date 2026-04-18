"""
Telemetry Exporter — Phase 2

Writes operational + financial telemetry to field_telemetry and
iam_temporal_events tables using the existing PostgreSQL database.

Uses SQLAlchemy Core Table definitions for cross-database compatibility
(SQLite for tests, PostgreSQL in production). TimescaleDB hypertable calls
are stubbed gracefully — tables work without the TimescaleDB extension.

Note: PostgreSQL stores unquoted column names in lowercase. Column names in this
module intentionally use lowercase to match the stored schema.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    select,
    text,
)

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

_metadata = MetaData()

field_telemetry = Table(
    "field_telemetry",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("time", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
    Column("identity_id", String(255)),
    Column("s", Float),
    Column("delta_s", Float),
    Column("q", Float),
    Column("tau", Float),
    Column("nabla_phi", Float),
    Column("field_state", String(64)),
    Column("float_yield", Float),
    Column("liquidity_signal", Float),
    Column("coherence_signal", Float),
    Column("r_hsce", Float),
    Column("float_reinvestment_rate", Float),
    Column("schema_version", String(16)),
)

iam_temporal_events = Table(
    "iam_temporal_events",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("time", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
    Column("identity_id", String(255)),
    Column("event_type", String(128)),
    Column("s", Float),
    Column("d", Float),
    Column("ttau", Float),
    Column("admitted", Boolean),
    Column("active_policies", Text),
)


class TelemetryExporter:
    """
    Writes telemetry to PostgreSQL (field_telemetry + iam_temporal_events).
    Falls back to a no-op stub when DATABASE_URL is not set.
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        self._url = database_url if database_url is not None else DATABASE_URL
        self._engine = None
        self._initialized = False
        if self._url:
            self._init_engine()

    def _init_engine(self) -> None:
        try:
            kwargs: Dict[str, Any] = {"pool_pre_ping": True}
            if self._url.startswith("sqlite"):
                kwargs["connect_args"] = {"check_same_thread": False}
            else:
                kwargs["pool_size"] = 3
                kwargs["max_overflow"] = 5

            self._engine = create_engine(self._url, **kwargs)
            _metadata.create_all(self._engine)
            self._try_create_hypertables()
            self._initialized = True
            logger.info("TelemetryExporter: tables initialised")
        except Exception as exc:
            logger.warning("TelemetryExporter: init failed (%s) — operating in stub mode", exc)
            self._engine = None

    def _try_create_hypertables(self) -> None:
        """
        Attempt to create TimescaleDB hypertables.
        Silently skips if the extension is not installed.
        """
        for table in ("field_telemetry", "iam_temporal_events"):
            try:
                with self._engine.connect() as conn:
                    conn.execute(
                        text(
                            "SELECT create_hypertable(:t, 'time', if_not_exists => TRUE)"
                        ),
                        {"t": table},
                    )
                    conn.commit()
                logger.info("TimescaleDB hypertable created for %s", table)
            except Exception:
                pass  # Extension not available — standard table is fine

    def insert_field_telemetry(self, record: Dict[str, Any]) -> None:
        """Insert one row into field_telemetry."""
        if not self._initialized or self._engine is None:
            logger.debug("TelemetryExporter stub: would insert field_telemetry %s", record)
            return
        try:
            with self._engine.connect() as conn:
                conn.execute(field_telemetry.insert().values(
                    time=record.get("time", datetime.now(timezone.utc)),
                    identity_id=record.get("identity_id"),
                    s=record.get("S", record.get("s")),
                    delta_s=record.get("delta_S", record.get("delta_s")),
                    q=record.get("Q", record.get("q")),
                    tau=record.get("tau"),
                    nabla_phi=record.get("nabla_phi"),
                    field_state=record.get("field_state"),
                    float_yield=record.get("float_yield"),
                    liquidity_signal=record.get("liquidity_signal"),
                    coherence_signal=record.get("coherence_signal"),
                    r_hsce=record.get("r_HSCE", record.get("r_hsce")),
                    float_reinvestment_rate=record.get("float_reinvestment_rate"),
                    schema_version=record.get("schema_version", "2.0"),
                ))
                conn.commit()
        except Exception as exc:
            logger.error("TelemetryExporter: insert_field_telemetry failed: %s", exc)

    def insert_iam_event(self, record: Dict[str, Any]) -> None:
        """Insert one row into iam_temporal_events."""
        if not self._initialized or self._engine is None:
            logger.debug("TelemetryExporter stub: would insert iam_temporal_events %s", record)
            return
        try:
            with self._engine.connect() as conn:
                conn.execute(iam_temporal_events.insert().values(
                    time=record.get("time", datetime.now(timezone.utc)),
                    identity_id=record.get("identity_id"),
                    event_type=record.get("event_type"),
                    s=record.get("S", record.get("s")),
                    d=record.get("D", record.get("d")),
                    ttau=record.get("Ttau", record.get("ttau")),
                    admitted=record.get("admitted"),
                    active_policies=str(record.get("active_policies", [])),
                ))
                conn.commit()
        except Exception as exc:
            logger.error("TelemetryExporter: insert_iam_event failed: %s", exc)

    def get_s_n_days_ago(self, n: int) -> Optional[float]:
        """
        Return the S value recorded approximately N days ago from field_telemetry.
        Returns None when not enough history exists.
        """
        if not self._initialized or self._engine is None:
            return None
        target_time = datetime.now(timezone.utc) - timedelta(days=n)
        try:
            with self._engine.connect() as conn:
                result = conn.execute(
                    select(field_telemetry.c.s)
                    .where(field_telemetry.c.time <= target_time)
                    .order_by(field_telemetry.c.time.desc())
                    .limit(1)
                )
                row = result.fetchone()
            if row is None:
                logger.warning("get_s_n_days_ago(%d): no record found", n)
                return None
            return float(row[0])
        except Exception as exc:
            logger.warning("get_s_n_days_ago(%d) failed: %s", n, exc)
            return None

    def get_q_variance(self, cycles: int = 7) -> float:
        """
        Compute variance of Q over the last N records in field_telemetry.
        Returns 0.0 when insufficient data exists.
        """
        if not self._initialized or self._engine is None:
            return 0.0
        try:
            with self._engine.connect() as conn:
                result = conn.execute(
                    select(field_telemetry.c.q)
                    .order_by(field_telemetry.c.time.desc())
                    .limit(cycles)
                )
                rows = result.fetchall()
            values = [float(r[0]) for r in rows if r[0] is not None]
            if len(values) < 2:
                return 0.0
            mean = sum(values) / len(values)
            return sum((v - mean) ** 2 for v in values) / len(values)
        except Exception as exc:
            logger.warning("get_q_variance failed: %s", exc)
            return 0.0

    def get_recent_field_telemetry(self, days: int = 30) -> List[Dict[str, Any]]:
        """Return last N days of field_telemetry rows as dicts."""
        if not self._initialized or self._engine is None:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        try:
            with self._engine.connect() as conn:
                result = conn.execute(
                    select(field_telemetry)
                    .where(field_telemetry.c.time >= cutoff)
                    .order_by(field_telemetry.c.time.desc())
                )
                rows = result.fetchall()
                keys = list(result.keys())
            raw = [dict(zip(keys, row)) for row in rows]
            # Normalize uppercase aliases for compatibility with callers using S, Q, etc.
            normalized = []
            for r in raw:
                r2 = dict(r)
                for lo, hi in [("s", "S"), ("delta_s", "delta_S"), ("q", "Q"), ("r_hsce", "r_HSCE")]:
                    if lo in r2:
                        r2[hi] = r2[lo]
                normalized.append(r2)
            return normalized
        except Exception as exc:
            logger.error("get_recent_field_telemetry failed: %s", exc)
            return []
