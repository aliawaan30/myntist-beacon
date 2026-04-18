import os
os.environ.setdefault("SUBSTRATE_HMAC_SECRET", "dev_secret_67890")

"""
Tests for iam-substrate/webhooks/hmac_handler.py
"""
import hashlib
import hmac
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from iam_substrate.webhooks.hmac_handler import verify_signature, sign_payload, HMAC_SECRET


SECRET = HMAC_SECRET
TEST_BODY = b'{"identity_id": "test-001", "event_type": "token_issued"}'


def _make_signature(body: bytes, secret: str = SECRET) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


class TestHmacHandler:
    def test_valid_signature_passes(self):
        """Valid signature should return True."""
        sig = _make_signature(TEST_BODY)
        assert verify_signature(TEST_BODY, sig) is True

    def test_invalid_signature_returns_false(self):
        """Invalid signature should return False."""
        assert verify_signature(TEST_BODY, "sha256=badhex") is False

    def test_tampered_payload_fails(self):
        """A signature computed for original body fails for tampered body."""
        sig = _make_signature(TEST_BODY)
        tampered_body = TEST_BODY + b" tampered"
        assert verify_signature(tampered_body, sig) is False

    def test_missing_signature_returns_false(self):
        """No signature header should return False."""
        assert verify_signature(TEST_BODY, None) is False

    def test_empty_signature_returns_false(self):
        assert verify_signature(TEST_BODY, "") is False

    def test_sign_payload_produces_valid_signature(self):
        """sign_payload output is verifiable by verify_signature."""
        sig = sign_payload(TEST_BODY)
        assert verify_signature(TEST_BODY, sig) is True

    def test_sign_payload_format(self):
        """sign_payload returns sha256=<hex> format."""
        sig = sign_payload(TEST_BODY)
        assert sig.startswith("sha256=")
        assert len(sig) == 7 + 64

    def test_wrong_secret_fails(self):
        """Signature with different secret fails verification."""
        sig = _make_signature(TEST_BODY, secret="wrong_secret")
        assert verify_signature(TEST_BODY, sig) is False

    def test_empty_body_valid_signature(self):
        """Empty body with correct signature should pass."""
        body = b""
        sig = _make_signature(body)
        assert verify_signature(body, sig) is True
