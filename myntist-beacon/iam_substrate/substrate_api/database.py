"""
Database session management for the IAM Substrate API.
Phase 2: init_db() adds Phase 2 columns to the telemetry table if missing.
"""
from __future__ import annotations

import logging
import os
from typing import Generator

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./iam_substrate.db")

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine
    if _engine is None:
        from sqlalchemy import create_engine
        url = DATABASE_URL
        kwargs: dict = {
            "pool_pre_ping": True,
        }
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 10
        _engine = create_engine(url, **kwargs)
    return _engine


def _get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        from sqlalchemy.orm import sessionmaker
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_get_engine())
    return _SessionLocal


def get_session_local():
    """Return the session factory (callable). Use for scripts and schedulers."""
    return _get_session_factory()


def get_db() -> Generator:
    """FastAPI dependency for database sessions."""
    SessionLocal = _get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_phase2_columns() -> None:
    """
    Add Phase 2 columns to the telemetry table if they don't already exist.
    Uses IF NOT EXISTS for idempotent execution (PostgreSQL 9.6+).
    Silently skips if the database is SQLite.
    """
    from sqlalchemy import text
    engine = _get_engine()
    url = str(engine.url)

    phase2_columns = [
        ("liquidity_signal", "DOUBLE PRECISION"),
        ("coherence_signal", "DOUBLE PRECISION"),
        ("admitted", "BOOLEAN"),
        ("active_policies", "TEXT"),
    ]

    if url.startswith("sqlite"):
        logger.info("Phase 2 column migration: SQLite detected — using CREATE TABLE path")
        return

    with engine.connect() as conn:
        for col_name, col_type in phase2_columns:
            try:
                conn.execute(text(
                    f"ALTER TABLE telemetry ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                ))
                conn.commit()
                logger.info("Phase 2 migration: ensured column telemetry.%s (%s)", col_name, col_type)
            except Exception as exc:
                logger.warning("Phase 2 migration: could not add column %s: %s", col_name, exc)
                try:
                    conn.rollback()
                except Exception:
                    pass


def init_db() -> None:
    """Create all tables if they don't exist, then apply Phase 2 column migrations."""
    from .models import Base
    Base.metadata.create_all(bind=_get_engine())
    _migrate_phase2_columns()
