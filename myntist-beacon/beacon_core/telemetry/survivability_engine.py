"""
Survivability Engine — computes S(t) = (1 / Q(t)) * cos(nabla_phi(t)) * tau(t)
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SurvivabilityResult:
    S: float
    delta_S: float
    field_state: str
    timestamp: float


class SurvivabilityEngine:
    """
    Computes the survivability score S(t) and tracks delta_S across calls.

    Formula:  S(t) = (1 / Q(t)) * cos(nabla_phi(t)) * tau(t)

    field_state:
        S >= 0.85  → stable
        S >= 0.70  → excitation
        S <  0.70  → incident
    """

    def __init__(self) -> None:
        self._last_S: Optional[float] = None

    def compute(self, Q: float, nabla_phi: float, tau: float) -> SurvivabilityResult:
        """
        Compute survivability score.

        Args:
            Q:          Quality / coherence degradation factor (must be > 0)
            nabla_phi:  Phase gradient (radians)
            tau:        Trust anchor score (0.0 – 1.0)

        Returns:
            SurvivabilityResult with S, delta_S, field_state, timestamp
        """
        if Q <= 0:
            raise ValueError(f"Q must be positive, got {Q}")

        S: float = (1.0 / Q) * math.cos(nabla_phi) * tau

        delta_S: float = S - self._last_S if self._last_S is not None else 0.0
        self._last_S = S

        field_state = self._classify(S)

        return SurvivabilityResult(
            S=S,
            delta_S=delta_S,
            field_state=field_state,
            timestamp=time.time(),
        )

    def reset(self) -> None:
        """Reset stored last_S (useful for tests)."""
        self._last_S = None

    @property
    def last_S(self) -> Optional[float]:
        return self._last_S

    @staticmethod
    def _classify(S: float) -> str:
        if S >= 0.85:
            return "stable"
        if S >= 0.70:
            return "excitation"
        return "incident"


_engine = SurvivabilityEngine()


def compute_survivability(Q: float, nabla_phi: float, tau: float) -> SurvivabilityResult:
    """Module-level convenience function using a shared singleton engine."""
    return _engine.compute(Q, nabla_phi, tau)


def get_engine() -> SurvivabilityEngine:
    return _engine
