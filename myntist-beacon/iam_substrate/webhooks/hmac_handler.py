"""
HMAC webhook handler — verifies inbound and signs outbound webhooks.

Header: X-Substrate-Signature: sha256=<hex>
Secret: SUBSTRATE_HMAC_SECRET env var
Returns 401 on invalid signature.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from fastapi import Request, HTTPException


HMAC_SECRET = os.getenv("SUBSTRATE_HMAC_SECRET", "")


def _compute_signature(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_signature(body: bytes, signature_header: Optional[str]) -> bool:
    """Return True if the X-Substrate-Signature header is valid."""
    if not signature_header:
        return False
    expected = _compute_signature(body, HMAC_SECRET)
    return hmac.compare_digest(expected, signature_header)


def sign_payload(body: bytes, secret: Optional[str] = None) -> str:
    """Return X-Substrate-Signature header value for an outbound payload."""
    s = secret or HMAC_SECRET
    return _compute_signature(body, s)


async def require_valid_signature(request: Request) -> bytes:
    """
    FastAPI dependency that reads the request body and validates the HMAC.
    Raises HTTPException(401) on failure.
    Returns the raw body bytes on success.
    """
    body = await request.body()
    sig = request.headers.get("X-Substrate-Signature")
    if not verify_signature(body, sig):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")
    return body
