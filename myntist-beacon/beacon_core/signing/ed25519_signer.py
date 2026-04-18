"""
ed25519_signer.py

Ed25519 signing and verification for beacon feeds.

- Signs status.json with the Ed25519 private key stored in ED25519_PRIVATE_KEY_HEX.
- Verifies signatures for the /api/field/v1/verify endpoint.
- Builds the /.well-known/field-signing-keys.json W3C document.

Private key is NEVER exposed in any response.
"""
from __future__ import annotations

import base64
import datetime
import os
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    PrivateFormat,
    NoEncryption,
)
from cryptography.exceptions import InvalidSignature
import base58

PRIVATE_KEY_HEX = os.getenv("ED25519_PRIVATE_KEY_HEX", "")
KEY_CREATED = os.getenv("ED25519_KEY_CREATED", "")
CONTROLLER = "https://myntist.com"
KEY_ID = f"{CONTROLLER}/.well-known/field-signing-keys.json#key-01"
KMS_KEY_ALIAS = os.getenv("KMS_KEY_ID", "alias/trust-ledger-kms-key-01")


def _load_private_key() -> Optional[Ed25519PrivateKey]:
    if not PRIVATE_KEY_HEX:
        return None
    try:
        raw = bytes.fromhex(PRIVATE_KEY_HEX)
        return Ed25519PrivateKey.from_private_bytes(raw)
    except Exception:
        return None


def _load_public_key() -> Optional[Ed25519PublicKey]:
    pk = _load_private_key()
    return pk.public_key() if pk else None


def _public_key_multibase() -> Optional[str]:
    pub = _load_public_key()
    if not pub:
        return None
    raw = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return "z" + base58.b58encode(raw).decode()


def sign(payload_bytes: bytes) -> Optional[str]:
    """
    Sign arbitrary bytes with the Ed25519 private key.

    Returns:
        "ed25519:<base64url-encoded-signature>" or None if key not configured.
    """
    pk = _load_private_key()
    if not pk:
        return None
    sig_bytes = pk.sign(payload_bytes)
    b64 = base64.urlsafe_b64encode(sig_bytes).rstrip(b"=").decode()
    return f"ed25519:{b64}"


def verify(payload_bytes: bytes, signature: str) -> bool:
    """
    Verify an Ed25519 signature produced by sign().

    Args:
        payload_bytes: the canonical JSON bytes that were signed.
        signature:     the "ed25519:<base64url>" string from the payload.

    Returns:
        True if valid, False otherwise.
    """
    pub = _load_public_key()
    if not pub:
        return False
    if not signature.startswith("ed25519:"):
        return False
    b64 = signature[len("ed25519:"):]
    # restore padding
    padding = 4 - len(b64) % 4
    if padding != 4:
        b64 += "=" * padding
    try:
        sig_bytes = base64.urlsafe_b64decode(b64)
        pub.verify(sig_bytes, payload_bytes)
        return True
    except (InvalidSignature, Exception):
        return False


def build_well_known() -> Dict[str, Any]:
    """
    Build the /.well-known/field-signing-keys.json W3C document.
    """
    multibase = _public_key_multibase()

    created = KEY_CREATED or datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    try:
        dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
        expires = (dt.replace(year=dt.year + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        expires = ""

    if multibase:
        return {
            "@context": "https://w3id.org/security/v2",
            "id": KEY_ID,
            "type": "Ed25519VerificationKey2020",
            "controller": CONTROLLER,
            "publicKeyMultibase": multibase,
            "created": created,
            "expires": expires,
            "schema_version": "2.0",
            "kms_key_id": KMS_KEY_ALIAS,
            "note": "Ed25519 signing key — AWS KMS key alias/trust-ledger-kms-key-01 — active since 2026-04-17",
        }

    return {
        "@context": "https://w3id.org/security/v2",
        "id": KEY_ID,
        "type": "Ed25519VerificationKey2020",
        "controller": CONTROLLER,
        "publicKeyMultibase": None,
        "created": created,
        "expires": expires,
        "schema_version": "2.0",
        "kms_key_id": KMS_KEY_ALIAS,
        "note": "ED25519_PRIVATE_KEY_HEX not configured — public key unavailable",
    }
