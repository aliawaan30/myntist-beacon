"""
Tests for iam_substrate/substrate_api/policy_engine.py — Phase 2
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from iam_substrate.substrate_api import policy_engine
from iam_substrate.substrate_api.policy_engine import (
    evaluate,
    reset_ttau_breach_count,
    get_active_policies,
)


def _ctx(**kwargs):
    defaults = {
        "S": 0.9,
        "delta_S": 0.0,
        "Q": 1.0,
        "tau": 1.0,
        "nabla_phi": 0.0,
        "field_state": "stable",
        "D": 0.15,
        "Ttau": 0.10,
    }
    defaults.update(kwargs)
    return defaults


class TestPolicyEngine:
    def setup_method(self):
        reset_ttau_breach_count()

    # ── Normal / admitted ────────────────────────────────────────────────────

    def test_stable_state_is_admitted(self):
        result = evaluate(_ctx())
        assert result["admitted"] is True

    def test_active_policy_ids_empty_when_no_triggers(self):
        result = evaluate(_ctx())
        assert result["active_policy_ids"] == []

    # ── P001: Low Liquidity Token Block ──────────────────────────────────────

    def test_p001_blocks_token_issued_when_D_low(self):
        result = evaluate(_ctx(D=0.05), event_type="token_issued")
        assert "P001" in result["active_policy_ids"]
        assert result["admitted"] is False

    def test_p001_does_not_block_other_events_when_D_low(self):
        """P001 only applies to token_issued events."""
        result = evaluate(_ctx(D=0.05), event_type="login")
        assert "P001" not in result["active_policy_ids"]

    def test_p001_does_not_activate_when_D_at_threshold(self):
        """D == 0.10 should not trigger P001 (threshold is lt, not le)."""
        result = evaluate(_ctx(D=0.10), event_type="token_issued")
        assert "P001" not in result["active_policy_ids"]

    # ── P003: Critical Survivability Block ───────────────────────────────────

    def test_p003_blocks_when_S_below_050(self):
        result = evaluate(_ctx(S=0.49))
        assert "P003" in result["active_policy_ids"]
        assert result["admitted"] is False

    def test_p003_does_not_activate_at_050(self):
        """S == 0.50 is not below threshold."""
        result = evaluate(_ctx(S=0.50))
        assert "P003" not in result["active_policy_ids"]

    def test_p003_does_not_activate_above_050(self):
        result = evaluate(_ctx(S=0.75))
        assert "P003" not in result["active_policy_ids"]

    # ── P004: Excitation State Throttle ─────────────────────────────────────

    def test_p004_throttles_during_excitation(self):
        result = evaluate(_ctx(field_state="excitation"))
        assert "P004" in result["active_policy_ids"]
        assert result["throttle_rate"] is not None
        assert abs(result["throttle_rate"] - 0.75) < 1e-9

    def test_p004_does_not_activate_in_stable(self):
        result = evaluate(_ctx(field_state="stable"))
        assert "P004" not in result["active_policy_ids"]

    def test_p004_does_not_activate_in_incident(self):
        result = evaluate(_ctx(field_state="incident"))
        assert "P004" not in result["active_policy_ids"]

    # ── P002: Ttau Sustained Breach ──────────────────────────────────────────

    def test_p002_does_not_activate_before_3_consecutive_breaches(self):
        for _ in range(2):
            result = evaluate(_ctx(Ttau=0.30))
        assert "P002" not in result["active_policy_ids"]

    def test_p002_activates_after_3_consecutive_breaches(self):
        for _ in range(3):
            result = evaluate(_ctx(Ttau=0.30))
        assert "P002" in result["active_policy_ids"]

    def test_p002_resets_when_ttau_below_threshold(self):
        for _ in range(3):
            evaluate(_ctx(Ttau=0.30))
        evaluate(_ctx(Ttau=0.10))
        result = evaluate(_ctx(Ttau=0.30))
        assert "P002" not in result["active_policy_ids"]

    def test_p002_throttle_rate_is_050(self):
        for _ in range(3):
            result = evaluate(_ctx(Ttau=0.30))
        assert abs(result["throttle_rate"] - 0.50) < 1e-9

    # ── Most severe policy wins ───────────────────────────────────────────────

    def test_block_overrides_throttle(self):
        """S < 0.50 (block P003) + excitation (throttle P004) → admitted=False."""
        result = evaluate(_ctx(S=0.49, field_state="excitation"))
        assert result["admitted"] is False

    def test_get_active_policies_returns_list(self):
        policies = get_active_policies()
        assert isinstance(policies, list)
        assert len(policies) >= 4

    def test_get_active_policies_have_ids(self):
        policies = get_active_policies()
        ids = [p["id"] for p in policies]
        for pid in ["P001", "P002", "P003", "P004"]:
            assert pid in ids, f"Policy {pid} not found in loaded policies"
