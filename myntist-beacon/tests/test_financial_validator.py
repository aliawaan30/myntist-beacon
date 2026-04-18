"""
Tests for beacon_core/telemetry/financial_validator.py — Phase 2
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from beacon_core.telemetry.financial_validator import validate


def _good_payload(**overrides):
    payload = {
        "schema_version": "2.0",
        "S": 0.9,
        "delta_S": 0.01,
        "float_yield": 0.008,
        "float_reinvestment_rate": 0.63,
        "r_HSCE": 0.012,
        "liquidity_signal": 0.15,
        "coherence_signal": 0.05,
    }
    payload.update(overrides)
    return payload


class TestFinancialValidator:

    def test_valid_payload_passes(self):
        ok, errors = validate(_good_payload())
        assert ok is True
        assert errors == []

    def test_missing_float_yield_fails(self):
        payload = _good_payload()
        payload["float_yield"] = None
        ok, errors = validate(payload)
        assert ok is False
        assert any("float_yield" in e for e in errors)

    def test_negative_float_yield_with_positive_delta_S_fails(self):
        payload = _good_payload(float_yield=-0.001, delta_S=0.01)
        ok, errors = validate(payload)
        assert ok is False
        assert any("float_yield" in e for e in errors)

    def test_negative_float_yield_with_negative_delta_S_passes(self):
        """When delta_S < 0, negative float_yield is allowed."""
        payload = _good_payload(float_yield=-0.001, delta_S=-0.05)
        ok, errors = validate(payload)
        assert ok is True

    def test_float_reinvestment_rate_above_1_fails(self):
        payload = _good_payload(float_reinvestment_rate=1.1)
        ok, errors = validate(payload)
        assert ok is False
        assert any("float_reinvestment_rate" in e for e in errors)

    def test_float_reinvestment_rate_below_0_fails(self):
        payload = _good_payload(float_reinvestment_rate=-0.01)
        ok, errors = validate(payload)
        assert ok is False

    def test_float_reinvestment_rate_boundary_0_passes(self):
        payload = _good_payload(float_reinvestment_rate=0.0)
        ok, errors = validate(payload)
        assert ok is True

    def test_float_reinvestment_rate_boundary_1_passes(self):
        payload = _good_payload(float_reinvestment_rate=1.0)
        ok, errors = validate(payload)
        assert ok is True

    def test_r_hsce_none_fails(self):
        payload = _good_payload(r_HSCE=None)
        ok, errors = validate(payload)
        assert ok is False
        assert any("r_HSCE" in e for e in errors)

    def test_liquidity_signal_missing_fails(self):
        payload = _good_payload(liquidity_signal=None)
        ok, errors = validate(payload)
        assert ok is False
        assert any("liquidity_signal" in e for e in errors)

    def test_wrong_schema_version_fails(self):
        payload = _good_payload(schema_version="1.0")
        ok, errors = validate(payload)
        assert ok is False
        assert any("schema_version" in e for e in errors)

    def test_schema_version_20_passes(self):
        payload = _good_payload(schema_version="2.0")
        ok, errors = validate(payload)
        assert ok is True

    def test_multiple_errors_returned(self):
        payload = _good_payload(r_HSCE=None, schema_version="1.0", float_yield=None)
        ok, errors = validate(payload)
        assert ok is False
        assert len(errors) >= 3

    def test_zero_float_yield_with_zero_delta_S_passes(self):
        """delta_S == 0 means float_yield >= 0 required; 0.0 is ok."""
        payload = _good_payload(float_yield=0.0, delta_S=0.0)
        ok, errors = validate(payload)
        assert ok is True

    def test_negative_liquidity_signal_fails(self):
        """liquidity_signal must be >= 0.0."""
        payload = _good_payload(liquidity_signal=-0.05)
        ok, errors = validate(payload)
        assert ok is False
        assert any("liquidity_signal" in e for e in errors)

    def test_zero_liquidity_signal_passes(self):
        """liquidity_signal == 0.0 is the boundary and must pass."""
        payload = _good_payload(liquidity_signal=0.0)
        ok, errors = validate(payload)
        assert ok is True

    def test_coherence_signal_missing_fails(self):
        """coherence_signal must not be None."""
        payload = _good_payload()
        payload["coherence_signal"] = None
        ok, errors = validate(payload)
        assert ok is False
        assert any("coherence_signal" in e for e in errors)

    def test_coherence_signal_zero_passes(self):
        """coherence_signal == 0.0 (clamped by epsilon floor) is valid."""
        payload = _good_payload(coherence_signal=0.0)
        ok, errors = validate(payload)
        assert ok is True
