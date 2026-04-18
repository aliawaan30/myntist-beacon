"""
Tests for beacon_core/telemetry/financial_engine.py — Phase 2
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from beacon_core.telemetry.financial_engine import FinancialEngine


class TestFinancialEngine:
    def setup_method(self):
        self.engine = FinancialEngine()

    # ── compute_float_yield ──────────────────────────────────────────────────

    def test_float_yield_positive_delta_S(self):
        """Positive delta_S gives positive float_yield."""
        result = self.engine.compute_float_yield(delta_S=0.05)
        assert result > 0

    def test_float_yield_negative_delta_S(self):
        """Negative delta_S gives negative float_yield."""
        result = self.engine.compute_float_yield(delta_S=-0.05)
        assert result < 0

    def test_float_yield_zero_delta_S(self):
        """Zero delta_S gives zero float_yield."""
        result = self.engine.compute_float_yield(delta_S=0.0)
        assert result == 0.0

    def test_float_yield_formula(self):
        """float_yield = delta_S / OPEX_BASELINE * 86400"""
        delta_S = 0.01
        opex = float(os.getenv("OPEX_BASELINE_USD", "500.00"))
        expected = delta_S / opex * 86400
        result = self.engine.compute_float_yield(delta_S=delta_S)
        assert abs(result - expected) < 1e-9

    # ── compute_liquidity_signal ─────────────────────────────────────────────

    def test_liquidity_signal_basic(self):
        """D = delta_S / (Q * delta_t)"""
        D = self.engine.compute_liquidity_signal(delta_S=0.1, Q=1.0, delta_t=100)
        assert abs(D - 0.001) < 1e-9

    def test_liquidity_signal_zero_Q_returns_zero(self):
        """Q=0 returns 0.0 (no division by zero)."""
        D = self.engine.compute_liquidity_signal(delta_S=0.1, Q=0.0)
        assert D == 0.0

    def test_liquidity_signal_zero_delta_t_returns_zero(self):
        """delta_t=0 returns 0.0."""
        D = self.engine.compute_liquidity_signal(delta_S=0.1, Q=1.0, delta_t=0)
        assert D == 0.0

    # ── compute_coherence_signal ─────────────────────────────────────────────

    def test_coherence_signal_basic(self):
        """Ttau = tau / q_variance"""
        Ttau = self.engine.compute_coherence_signal(tau=1.0, q_variance=4.0)
        assert abs(Ttau - 0.25) < 1e-9

    def test_coherence_signal_zero_variance_returns_zero(self):
        """q_variance=0 → Ttau=0.0."""
        Ttau = self.engine.compute_coherence_signal(tau=1.0, q_variance=0.0)
        assert Ttau == 0.0

    # ── compute_r_hsce ───────────────────────────────────────────────────────

    def test_r_hsce_none_without_client(self):
        """Returns None when no timescale_client provided."""
        result = self.engine.compute_r_hsce(current_S=0.9, timescale_client=None)
        assert result is None

    def test_r_hsce_none_when_history_insufficient(self):
        """Returns None when timescale_client.get_s_n_days_ago() returns None."""
        class StubClient:
            def get_s_n_days_ago(self, n):
                return None
        result = self.engine.compute_r_hsce(current_S=0.9, timescale_client=StubClient())
        assert result is None

    def test_r_hsce_computes_correctly(self):
        """r_HSCE = (S_now - S_N_days_ago) / window"""
        class StubClient:
            def get_s_n_days_ago(self, n):
                return 0.80
        engine = FinancialEngine()
        result = engine.compute_r_hsce(current_S=0.90, timescale_client=StubClient())
        window = int(os.getenv("R_HSCE_SMOOTHING_WINDOW", "7"))
        expected = (0.90 - 0.80) / window
        assert abs(result - expected) < 1e-9

    def test_r_hsce_negative_when_S_declined(self):
        """r_HSCE is negative when S has decreased."""
        class StubClient:
            def get_s_n_days_ago(self, n):
                return 0.95
        result = self.engine.compute_r_hsce(current_S=0.70, timescale_client=StubClient())
        assert result < 0

    # ── compute_all ──────────────────────────────────────────────────────────

    def test_compute_all_returns_all_fields(self):
        """compute_all returns dict with all 6 financial fields."""
        out = self.engine.compute_all(
            {"S": 0.9, "delta_S": 0.01, "Q": 1.0, "tau": 1.0, "nabla_phi": 0.0}
        )
        for field in [
            "float_yield", "liquidity_signal", "coherence_signal",
            "r_HSCE", "float_reinvestment_rate", "schema_version",
        ]:
            assert field in out, f"Missing field: {field}"

    def test_compute_all_schema_version_is_2(self):
        out = self.engine.compute_all(
            {"S": 0.9, "delta_S": 0.01, "Q": 1.0, "tau": 1.0}
        )
        assert out["schema_version"] == "2.0"

    def test_compute_all_float_reinvestment_rate_from_env(self):
        out = self.engine.compute_all(
            {"S": 0.9, "delta_S": 0.01, "Q": 1.0, "tau": 1.0}
        )
        expected = float(os.getenv("FLOAT_REINVESTMENT_RATE", "0.63"))
        assert abs(out["float_reinvestment_rate"] - expected) < 1e-9

    def test_q_variance_buffer_accumulates(self):
        for q in [1.0, 1.2, 0.8, 1.1, 0.9]:
            self.engine.update_q_buffer(q)
        variance = self.engine.get_q_variance()
        assert variance > 0

    def test_q_variance_single_value_returns_zero(self):
        engine = FinancialEngine()
        engine.update_q_buffer(1.0)
        assert engine.get_q_variance() == 0.0
