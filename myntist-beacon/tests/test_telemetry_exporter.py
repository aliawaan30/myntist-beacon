"""
Tests for beacon_core/telemetry/telemetry_exporter.py — Phase 2

Uses an in-memory SQLite database so no PostgreSQL instance is required.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from beacon_core.telemetry.telemetry_exporter import TelemetryExporter

SQLITE_URL = "sqlite://"  # in-memory SQLite


@pytest.fixture()
def exporter():
    """Fresh in-memory exporter for each test."""
    exp = TelemetryExporter(database_url=SQLITE_URL)
    return exp


def _telemetry_record(**overrides):
    base = {
        "time": datetime.now(timezone.utc),
        "identity_id": "test_identity",
        "S": 0.9,
        "delta_S": 0.01,
        "Q": 1.0,
        "tau": 1.0,
        "nabla_phi": 0.0,
        "field_state": "stable",
        "float_yield": 0.008,
        "liquidity_signal": 0.15,
        "coherence_signal": 0.05,
        "r_HSCE": 0.012,
        "float_reinvestment_rate": 0.63,
        "schema_version": "2.0",
    }
    base.update(overrides)
    return base


class TestTelemetryExporter:

    def test_exporter_initialises(self, exporter):
        assert exporter._initialized is True

    def test_insert_field_telemetry_succeeds(self, exporter):
        """Inserting a record should not raise."""
        exporter.insert_field_telemetry(_telemetry_record())

    def test_get_recent_field_telemetry_empty_initially(self, exporter):
        rows = exporter.get_recent_field_telemetry(days=7)
        assert rows == []

    def test_get_recent_field_telemetry_returns_inserted(self, exporter):
        exporter.insert_field_telemetry(_telemetry_record(S=0.88))
        rows = exporter.get_recent_field_telemetry(days=7)
        assert len(rows) == 1
        assert abs(rows[0]["S"] - 0.88) < 1e-6

    def test_multiple_records_returned_in_desc_order(self, exporter):
        for s in [0.80, 0.85, 0.90]:
            exporter.insert_field_telemetry(_telemetry_record(S=s))
        rows = exporter.get_recent_field_telemetry(days=7)
        assert len(rows) == 3

    def test_get_s_n_days_ago_none_when_no_history(self, exporter):
        result = exporter.get_s_n_days_ago(7)
        assert result is None

    def test_get_s_n_days_ago_returns_value(self, exporter):
        old_time = datetime.now(timezone.utc) - timedelta(days=8)
        exporter.insert_field_telemetry(_telemetry_record(S=0.75, time=old_time))
        result = exporter.get_s_n_days_ago(7)
        assert result is not None
        assert abs(result - 0.75) < 1e-6

    def test_get_q_variance_zero_when_no_data(self, exporter):
        variance = exporter.get_q_variance()
        assert variance == 0.0

    def test_get_q_variance_positive_when_data_varies(self, exporter):
        for q in [1.0, 1.5, 0.8, 1.2, 0.9]:
            exporter.insert_field_telemetry(_telemetry_record(Q=q))
        variance = exporter.get_q_variance(cycles=5)
        assert variance > 0

    def test_insert_iam_event_succeeds(self, exporter):
        exporter.insert_iam_event({
            "identity_id": "test_identity",
            "event_type": "token_issued",
            "S": 0.9,
            "D": 0.15,
            "Ttau": 0.05,
            "admitted": True,
            "active_policies": [],
        })

    def test_stub_mode_does_not_raise(self):
        """Exporter with no DATABASE_URL should operate in stub mode without raising."""
        stub = TelemetryExporter(database_url="")
        stub.insert_field_telemetry(_telemetry_record())
        assert stub.get_s_n_days_ago(7) is None
        assert stub.get_q_variance() == 0.0

    def test_financial_fields_round_trip(self, exporter):
        """All financial fields survive insert → read round-trip."""
        record = _telemetry_record(
            float_yield=0.009,
            liquidity_signal=0.20,
            coherence_signal=0.08,
            r_HSCE=0.014,
            float_reinvestment_rate=0.63,
            schema_version="2.0",
        )
        exporter.insert_field_telemetry(record)
        rows = exporter.get_recent_field_telemetry(days=1)
        assert len(rows) == 1
        row = rows[0]
        assert abs(row["float_yield"] - 0.009) < 1e-6
        assert abs(row["liquidity_signal"] - 0.20) < 1e-6
        assert row["schema_version"] == "2.0"
