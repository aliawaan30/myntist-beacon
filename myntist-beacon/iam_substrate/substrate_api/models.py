"""
SQLAlchemy ORM models for the IAM Substrate.
Phase 2: TelemetryRecord gains four new nullable columns.
"""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Text,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Identity(Base):
    __tablename__ = "identities"

    id = Column(String, primary_key=True)
    display_name = Column(String, nullable=True)
    S = Column(Float, default=1.0, nullable=False)
    Q = Column(Float, default=1.0, nullable=False)
    tau = Column(Float, default=1.0, nullable=False)
    nabla_phi = Column(Float, default=0.0, nullable=False)
    delta_S = Column(Float, default=0.0, nullable=False)
    field_state = Column(String, default="stable", nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class TelemetryRecord(Base):
    __tablename__ = "telemetry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    identity_id = Column(String, nullable=False)
    S = Column(Float, nullable=False)
    delta_S = Column(Float, nullable=False)
    Q = Column(Float, nullable=False)
    tau = Column(Float, nullable=False)
    nabla_phi = Column(Float, nullable=False)
    field_state = Column(String, nullable=False)
    mttr = Column(Float, nullable=True)
    hash = Column(String, nullable=True)
    recorded_at = Column(DateTime, server_default=func.now())
    # Phase 2 fields — nullable for backward compatibility
    liquidity_signal = Column(Float, nullable=True)
    coherence_signal = Column(Float, nullable=True)
    admitted = Column(Boolean, nullable=True)
    active_policies = Column(Text, nullable=True)


class AuditLogEntry(Base):
    """
    Append-only audit log with SHA-256 hash chain.
    DB constraint ensures no UPDATE or DELETE is possible via application logic.
    """
    __tablename__ = "iam_substrate_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False)
    identity_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    S_before = Column(Float, nullable=True)
    S_after = Column(Float, nullable=True)
    action = Column(Text, nullable=True)
    hash = Column(String(64), nullable=False)
    prev_hash = Column(String(64), nullable=False)
