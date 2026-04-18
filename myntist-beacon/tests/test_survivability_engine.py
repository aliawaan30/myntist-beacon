"""
Tests for beacon-core/telemetry/survivability_engine.py
"""
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from beacon_core.telemetry.survivability_engine import SurvivabilityEngine


class TestSurvivabilityEngine:
    def setup_method(self):
        self.engine = SurvivabilityEngine()

    def test_formula_correct_output(self):
        """S formula produces correct output for known inputs."""
        Q = 1.0
        nabla_phi = 0.0
        tau = 1.0
        result = self.engine.compute(Q, nabla_phi, tau)
        expected_S = (1.0 / Q) * math.cos(nabla_phi) * tau
        assert abs(result.S - expected_S) < 1e-9

    def test_formula_with_non_trivial_inputs(self):
        Q = 2.0
        nabla_phi = math.pi / 4
        tau = 0.9
        result = self.engine.compute(Q, nabla_phi, tau)
        expected_S = (1.0 / 2.0) * math.cos(math.pi / 4) * 0.9
        assert abs(result.S - expected_S) < 1e-9

    def test_field_state_stable(self):
        """S >= 0.85 → stable"""
        # Q=1, nabla_phi=0, tau=0.9 → S=0.9
        result = self.engine.compute(1.0, 0.0, 0.9)
        assert result.field_state == "stable"

    def test_field_state_excitation(self):
        """0.70 <= S < 0.85 → excitation"""
        # Q=1, nabla_phi=0, tau=0.75 → S=0.75
        result = self.engine.compute(1.0, 0.0, 0.75)
        assert result.field_state == "excitation"

    def test_field_state_incident(self):
        """S < 0.70 → incident"""
        # Q=2, nabla_phi=0, tau=1.0 → S=0.5
        result = self.engine.compute(2.0, 0.0, 1.0)
        assert result.field_state == "incident"

    def test_field_state_boundary_stable(self):
        """S exactly 0.85 → stable"""
        result = self.engine.compute(1.0, 0.0, 0.85)
        assert result.field_state == "stable"

    def test_field_state_boundary_excitation(self):
        """S exactly 0.70 → excitation"""
        result = self.engine.compute(1.0, 0.0, 0.70)
        assert result.field_state == "excitation"

    def test_delta_S_first_call_is_zero(self):
        """First call delta_S should be 0.0."""
        self.engine.reset()
        result = self.engine.compute(1.0, 0.0, 0.9)
        assert result.delta_S == 0.0

    def test_delta_S_calculates_correctly_across_calls(self):
        """delta_S is the difference between successive S values."""
        self.engine.reset()
        r1 = self.engine.compute(1.0, 0.0, 0.9)
        r2 = self.engine.compute(1.0, 0.0, 0.8)
        expected_delta = r2.S - r1.S
        assert abs(r2.delta_S - expected_delta) < 1e-9

    def test_delta_S_positive_when_S_increases(self):
        self.engine.reset()
        self.engine.compute(2.0, 0.0, 1.0)
        r2 = self.engine.compute(1.0, 0.0, 1.0)
        assert r2.delta_S > 0

    def test_delta_S_negative_when_S_decreases(self):
        self.engine.reset()
        self.engine.compute(1.0, 0.0, 1.0)
        r2 = self.engine.compute(2.0, 0.0, 1.0)
        assert r2.delta_S < 0

    def test_invalid_Q_raises(self):
        with pytest.raises(ValueError):
            self.engine.compute(0.0, 0.0, 1.0)

    def test_invalid_Q_negative_raises(self):
        with pytest.raises(ValueError):
            self.engine.compute(-1.0, 0.0, 1.0)

    def test_result_has_timestamp(self):
        result = self.engine.compute(1.0, 0.0, 1.0)
        assert result.timestamp > 0

    def test_reset_clears_last_S(self):
        self.engine.compute(1.0, 0.0, 0.9)
        self.engine.reset()
        result = self.engine.compute(1.0, 0.0, 0.8)
        assert result.delta_S == 0.0
