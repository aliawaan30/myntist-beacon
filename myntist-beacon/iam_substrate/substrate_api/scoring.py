"""
EMA scoring for identity survivability.

alpha = 0.3 (exponential moving average weight)

Event weights:
    token_issued      : +0.02
    role_change       : -0.01
    permission_update : +0.01
    token_revoked     : -0.05
"""
from __future__ import annotations

import math

ALPHA = 0.3

EVENT_WEIGHTS: dict[str, float] = {
    "token_issued": 0.02,
    "role_change": -0.01,
    "permission_update": 0.01,
    "token_revoked": -0.05,
}


def apply_event_weight(current_S: float, event_type: str) -> float:
    """
    Apply EMA-weighted event delta to current S.

    new_S = clamp(current_S + alpha * weight, 0.0, 1.0)
    """
    weight = EVENT_WEIGHTS.get(event_type, 0.0)
    delta = ALPHA * weight
    new_S = current_S + delta
    return max(0.0, min(1.0, new_S))


def score_from_inputs(Q: float, nabla_phi: float, tau: float):
    """Compute S from raw survivability inputs."""
    from beacon_core.telemetry.survivability_engine import compute_survivability
    return compute_survivability(Q, nabla_phi, tau)


def ema_blend(old_S: float, new_S: float, alpha: float = ALPHA) -> float:
    """Blend old and new S using EMA."""
    blended = alpha * new_S + (1 - alpha) * old_S
    return max(0.0, min(1.0, blended))
