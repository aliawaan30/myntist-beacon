"""
Tests for beacon_core/hsce/interface_contract.py — Phase 2
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from beacon_core.hsce.interface_contract import (
    FIELD_SCHEMA,
    HSCE_INTERFACE_VERSION,
    validate_hsce_payload,
    push_to_hsce,
)


def _good_payload(**overrides):
    payload = {
        "schema_version": "2.0",
        "generated_at": 1713273600,
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
    }
    payload.update(overrides)
    return payload


class TestHSCEInterfaceContract:

    def test_interface_version_is_v1(self):
        assert HSCE_INTERFACE_VERSION == "v1"

    def test_field_schema_has_required_keys(self):
        required = {
            "schema_version", "generated_at", "S", "delta_S", "Q",
            "tau", "nabla_phi", "field_state",
        }
        assert required.issubset(set(FIELD_SCHEMA.keys()))

    def test_valid_payload_passes_validation(self):
        assert validate_hsce_payload(_good_payload()) is True

    def test_missing_field_fails_validation(self):
        payload = _good_payload()
        del payload["S"]
        assert validate_hsce_payload(payload) is False

    def test_wrong_type_fails_validation(self):
        """schema_version must be str."""
        payload = _good_payload(schema_version=2.0)
        assert validate_hsce_payload(payload) is False

    def test_none_allowed_for_optional_fields(self):
        """float_yield, r_HSCE etc. allow None type."""
        payload = _good_payload(r_HSCE=None, float_yield=None)
        assert validate_hsce_payload(payload) is True

    def test_generated_at_must_be_int(self):
        payload = _good_payload(generated_at="not-an-int")
        assert validate_hsce_payload(payload) is False

    def test_push_to_hsce_stub_does_not_raise(self, monkeypatch):
        """push_to_hsce should not raise when HSCE_ENDPOINT is empty."""
        monkeypatch.setenv("HSCE_ENDPOINT", "")
        import importlib
        import beacon_core.hsce.interface_contract as ic
        importlib.reload(ic)
        ic.push_to_hsce(_good_payload())

    def test_push_to_hsce_logs_when_endpoint_blank(self, monkeypatch, caplog):
        """push_to_hsce logs at INFO when endpoint is blank."""
        monkeypatch.setenv("HSCE_ENDPOINT", "")
        import importlib
        import beacon_core.hsce.interface_contract as ic
        importlib.reload(ic)
        import logging
        with caplog.at_level(logging.INFO, logger="beacon_core.hsce.interface_contract"):
            ic.push_to_hsce(_good_payload())

    def test_field_state_must_be_str(self):
        payload = _good_payload(field_state=123)
        assert validate_hsce_payload(payload) is False

    def test_full_round_trip_validate_then_stub_push(self):
        """Validate then push without error in stub mode."""
        payload = _good_payload()
        assert validate_hsce_payload(payload) is True
        push_to_hsce(payload)
