"""
Financial Engine — Phase 2

Computes six financial telemetry fields from survivability output:
  float_yield, liquidity_signal, coherence_signal, r_HSCE,
  float_reinvestment_rate (constant), schema_version

All fields stub to 0.0 when ENABLE_FLOAT_ANALYTICS=false.
r_HSCE returns None when < R_HSCE_SMOOTHING_WINDOW days of history exist.
"""
from __future__ import annotations

import logging
import os
from collections import deque
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ENABLE_FLOAT_ANALYTICS = os.getenv("ENABLE_FLOAT_ANALYTICS", "true").lower() == "true"
OPEX_BASELINE_USD = float(os.getenv("OPEX_BASELINE_USD", "500.00"))
FLOAT_REINVESTMENT_RATE = float(os.getenv("FLOAT_REINVESTMENT_RATE", "0.63"))
R_HSCE_SMOOTHING_WINDOW = int(os.getenv("R_HSCE_SMOOTHING_WINDOW", "7"))


class FinancialEngine:
    """Computes Phase 2 financial telemetry from survivability output."""

    def __init__(self) -> None:
        self._q_variance_buffer: deque = deque(maxlen=R_HSCE_SMOOTHING_WINDOW)

    def compute_float_yield(self, delta_S: float) -> float:
        """
        Float yield per dollar per day.
        Negative when delta_S is negative (yield contraction).
        Formula: delta_S / OPEX_BASELINE_USD * 86400
        """
        if OPEX_BASELINE_USD == 0:
            return 0.0
        return delta_S / OPEX_BASELINE_USD * 86400

    def compute_liquidity_signal(
        self,
        delta_S: float,
        Q: float,
        delta_t: int = 600,
    ) -> float:
        """
        Dimensionless liquidity signal D.
        Formula: delta_S / (Q * delta_t)
        """
        if Q == 0 or delta_t == 0:
            return 0.0
        return max(0.0, delta_S / (Q * delta_t))

    _COHERENCE_MIN_VARIANCE = 1e-4  # epsilon floor to prevent near-zero division

    def compute_coherence_signal(self, tau: float, q_variance: float) -> float:
        """
        Coherence signal Ttau.
        Formula: tau / q_variance
        Returns 0.0 when q_variance is below the minimum meaningful threshold.
        A minimum variance floor prevents explosion from near-zero denominators
        when Q readings are tightly clustered (e.g. all 1.8).
        """
        if q_variance < self._COHERENCE_MIN_VARIANCE:
            return 0.0
        return tau / q_variance

    def compute_r_hsce(
        self,
        current_S: float,
        timescale_client: Any = None,
    ) -> Optional[float]:
        """
        Rate of HSCE field change per day.
        Formula: (S_current - S_N_days_ago) / R_HSCE_SMOOTHING_WINDOW
        Returns None when fewer than R_HSCE_SMOOTHING_WINDOW days of history exist.
        """
        if timescale_client is None:
            logger.warning("r_HSCE: no timescale_client provided — returning None")
            return None
        try:
            s_n_days_ago = timescale_client.get_s_n_days_ago(R_HSCE_SMOOTHING_WINDOW)
        except Exception as exc:
            logger.warning("r_HSCE: history lookup failed (%s) — returning None", exc)
            return None

        if s_n_days_ago is None:
            logger.warning(
                "r_HSCE: fewer than %d days of history — returning None",
                R_HSCE_SMOOTHING_WINDOW,
            )
            return None

        if R_HSCE_SMOOTHING_WINDOW == 0:
            return None

        return (current_S - s_n_days_ago) / R_HSCE_SMOOTHING_WINDOW

    def update_q_buffer(self, Q: float) -> None:
        """Track Q values for variance computation."""
        self._q_variance_buffer.append(Q)

    def get_q_variance(self) -> float:
        """Compute variance of the Q buffer."""
        buf = list(self._q_variance_buffer)
        if len(buf) < 2:
            return 0.0
        mean = sum(buf) / len(buf)
        return sum((x - mean) ** 2 for x in buf) / len(buf)

    def compute_all(
        self,
        survivability_output: Dict[str, Any],
        timescale_client: Any = None,
    ) -> Dict[str, Any]:
        """
        Compute all 6 Phase 2 financial fields.
        Stubs every field to 0.0 if ENABLE_FLOAT_ANALYTICS=false.
        """
        if not ENABLE_FLOAT_ANALYTICS:
            return {
                "float_yield": 0.0,
                "liquidity_signal": 0.0,
                "coherence_signal": 0.0,
                "r_HSCE": 0.0,
                "float_reinvestment_rate": 0.0,
                "schema_version": "2.0",
            }

        delta_S = survivability_output.get("delta_S", 0.0)
        Q = survivability_output.get("Q", 1.0)
        tau = survivability_output.get("tau", 1.0)
        current_S = survivability_output.get("S", 1.0)

        self.update_q_buffer(Q)
        q_variance = self.get_q_variance()

        float_yield = self.compute_float_yield(delta_S)
        liquidity_signal = self.compute_liquidity_signal(delta_S, Q)
        coherence_signal = self.compute_coherence_signal(tau, q_variance)
        r_hsce = self.compute_r_hsce(current_S, timescale_client)

        return {
            "float_yield": float_yield,
            "liquidity_signal": liquidity_signal,
            "coherence_signal": coherence_signal,
            "r_HSCE": r_hsce,
            "float_reinvestment_rate": FLOAT_REINVESTMENT_RATE,
            "schema_version": "2.0",
        }
