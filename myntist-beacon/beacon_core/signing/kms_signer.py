"""
kms_signer.py

Signs beacon payloads. Priority:
  1. ED25519_PRIVATE_KEY_HEX set → Ed25519 signature ("ed25519:<base64url>")
  2. KMS_KEY_ID set (real UUID/ARN) → AWS KMS RSASSA_PSS_SHA_256 (production)
  3. Neither → signature field omitted

Public beacon payload signing uses Ed25519 or KMS RSA only.
Internal webhook authentication is handled separately in webhooks/hmac_handler.py.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

KMS_KEY_ID = os.getenv("KMS_KEY_ID", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

_KMS_ALIAS_ONLY = KMS_KEY_ID.startswith("alias/")


def sign_bytes(raw: bytes) -> Optional[str]:
    """
    Sign pre-serialised bytes directly.

    This is the canonical signing primitive.  Use this whenever the caller
    has already produced the byte sequence that should be signed (e.g. the
    same bytes used to compute the payload hash) so that hash and signature
    always cover identical input.

    Returns:
        Signature string, or None if no signing key is configured.
        - Ed25519:   "ed25519:<base64url>"       (preferred)
        - KMS RSA:   base64-encoded RSASSA_PSS_SHA_256  (production)
    """
    from beacon_core.signing.ed25519_signer import sign as ed25519_sign, PRIVATE_KEY_HEX

    if PRIVATE_KEY_HEX:
        sig = ed25519_sign(raw)
        if sig:
            logger.info("Ed25519 signature applied")
            return sig
        logger.error("Ed25519 sign failed — signature omitted")
        return None

    if KMS_KEY_ID and not _KMS_ALIAS_ONLY:
        try:
            import boto3
            client = boto3.client("kms", region_name=AWS_REGION)
            response = client.sign(
                KeyId=KMS_KEY_ID,
                Message=raw,
                MessageType="RAW",
                SigningAlgorithm="RSASSA_PSS_SHA_256",
            )
            return base64.b64encode(response["Signature"]).decode()
        except Exception as exc:
            logger.error("KMS sign failed: %s — signature omitted", exc)
            return None

    logger.warning("No signing key configured — signature omitted")
    return None


def sign_payload(payload: Dict[str, Any]) -> Optional[str]:
    """
    Sign a JSON payload by serialising it then delegating to sign_bytes.

    Kept for backward compatibility with handlers that do not need a
    separate hash field.  For payloads that also carry a `hash` field,
    call sign_bytes() directly with the pre-hash canonical bytes instead.
    """
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    return sign_bytes(payload_bytes)
