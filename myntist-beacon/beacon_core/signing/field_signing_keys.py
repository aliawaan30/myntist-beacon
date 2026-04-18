"""
field_signing_keys.py

Builds the /.well-known/field-signing-keys.json document.
Delegates to ed25519_signer which holds the W3C Ed25519VerificationKey2020 logic.
"""
from __future__ import annotations

from typing import Any, Dict
from beacon_core.signing.ed25519_signer import build_well_known


def build() -> Dict[str, Any]:
    return build_well_known()
