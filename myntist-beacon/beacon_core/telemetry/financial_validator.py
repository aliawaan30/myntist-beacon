"""
Financial Validator — Phase 2

Validates the six Phase 2 financial fields before publishing.
Blocks the pipeline if any field is missing or out of range.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def validate(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate all 6 financial fields in the payload.

    Returns (True, []) when all checks pass.
    Returns (False, [error_messages]) when any check fails.
    """
    errors: List[str] = []

    float_yield = payload.get("float_yield")
    delta_S = payload.get("delta_S", 0.0)
    float_reinvestment_rate = payload.get("float_reinvestment_rate")
    r_hsce = payload.get("r_HSCE")
    liquidity_signal = payload.get("liquidity_signal")
    coherence_signal = payload.get("coherence_signal")
    schema_version = payload.get("schema_version")

    if float_yield is None:
        errors.append("float_yield must not be None")
    elif delta_S is not None and float(delta_S) >= 0.0 and float(float_yield) < 0.0:
        errors.append(
            f"float_yield must be >= 0.0 when delta_S >= 0, "
            f"got float_yield={float_yield} delta_S={delta_S}"
        )

    if float_reinvestment_rate is None:
        errors.append("float_reinvestment_rate must not be None")
    elif not (0.0 <= float(float_reinvestment_rate) <= 1.0):
        errors.append(
            f"float_reinvestment_rate must be in [0.0, 1.0], "
            f"got {float_reinvestment_rate}"
        )

    if r_hsce is None:
        errors.append(
            "r_HSCE must not be None — ensure at least "
            "R_HSCE_SMOOTHING_WINDOW days of telemetry history exist"
        )

    if liquidity_signal is None:
        errors.append("liquidity_signal must not be None")
    elif float(liquidity_signal) < 0.0:
        errors.append(
            f"liquidity_signal must be >= 0.0, got {liquidity_signal}"
        )

    if coherence_signal is None:
        errors.append("coherence_signal must not be None")

    if schema_version != "2.0":
        errors.append(f"schema_version must be '2.0', got '{schema_version}'")

    if errors:
        for msg in errors:
            logger.error("Financial validation failed: %s", msg)
        return False, errors

    return True, []
