"""
HSCE Interface Contract — Phase 2

Provides the schema definition, payload validator, and push function
for sending field data to the Heterogeneous Substrate Coherence Engine.

Set HSCE_ENDPOINT and HSCE_API_TOKEN to enable live delivery.
When HSCE_ENDPOINT is blank, push_to_hsce logs at INFO level only.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

HSCE_INTERFACE_VERSION = "v1"
HSCE_ENDPOINT = os.getenv("HSCE_ENDPOINT", "")
HSCE_API_TOKEN = os.getenv("HSCE_API_TOKEN", "")
HSCE_PUSH_TIMEOUT = int(os.getenv("HSCE_PUSH_TIMEOUT", "10"))

FIELD_SCHEMA: Dict[str, type] = {
    "schema_version": str,
    "generated_at": int,
    "S": float,
    "delta_S": float,
    "Q": float,
    "tau": float,
    "nabla_phi": float,
    "field_state": str,
    "float_yield": (float, type(None)),
    "liquidity_signal": (float, type(None)),
    "coherence_signal": (float, type(None)),
    "r_HSCE": (float, type(None)),
    "float_reinvestment_rate": (float, type(None)),
}


def validate_hsce_payload(payload: Dict[str, Any]) -> bool:
    """
    Validate a payload against FIELD_SCHEMA.
    Returns True when all required fields are present and correctly typed.
    """
    for field, expected_type in FIELD_SCHEMA.items():
        if field not in payload:
            logger.warning("HSCE validate: missing field '%s'", field)
            return False
        value = payload[field]
        if not isinstance(value, expected_type):
            logger.warning(
                "HSCE validate: field '%s' has type %s, expected %s",
                field,
                type(value).__name__,
                expected_type,
            )
            return False
    return True


def push_to_hsce(payload: Dict[str, Any]) -> None:
    """
    Push a validated field payload to the HSCE endpoint.

    - Logs at INFO level when HSCE_ENDPOINT is blank (stub mode).
    - POSTs with Bearer token when HSCE_ENDPOINT is set.
    - Retries once on timeout.
    """
    if not HSCE_ENDPOINT:
        logger.info(
            "HSCE push (stub): endpoint not configured — "
            "payload would be sent (schema_version=%s, S=%s)",
            payload.get("schema_version"),
            payload.get("S"),
        )
        return

    import requests

    headers = {
        "Content-Type": "application/json",
        "X-HSCE-Interface-Version": HSCE_INTERFACE_VERSION,
    }
    if HSCE_API_TOKEN:
        headers["Authorization"] = f"Bearer {HSCE_API_TOKEN}"

    attempt = 0
    while attempt < 2:
        attempt += 1
        try:
            resp = requests.post(
                HSCE_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=HSCE_PUSH_TIMEOUT,
            )
            resp.raise_for_status()
            logger.info("HSCE push succeeded (status=%d, attempt=%d)", resp.status_code, attempt)
            return
        except requests.exceptions.Timeout:
            if attempt < 2:
                logger.warning("HSCE push timed out on attempt %d — retrying", attempt)
                continue
            logger.error("HSCE push failed after 2 attempts (timeout)")
            return
        except Exception as exc:
            logger.error("HSCE push error (attempt %d): %s", attempt, exc)
            return
