"""
IPFS pinner via Pinata — stub implementation.

Pins content to IPFS. Returns mock CID if credentials not set.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

IPFS_API_URL = os.getenv("IPFS_API_URL", "https://api.pinata.cloud")
IPFS_API_KEY = os.getenv("IPFS_API_KEY", "")
IPFS_API_SECRET = os.getenv("IPFS_API_SECRET", "")


def pin_json(content: Dict[str, Any], name: str = "myntist-beacon") -> Dict[str, Any]:
    """
    Pin a JSON object to IPFS via Pinata.

    Returns:
        dict with cid, status
    """
    if not IPFS_API_KEY or not IPFS_API_SECRET:
        logger.info("IPFS credentials not set — returning mock CID (stub)")
        return {
            "status": "stub",
            # Stub: set IPFS_API_KEY + IPFS_API_SECRET for
            # real IPFS pinning
            "cid": "QmMockCID000000000000000000000000000000000000",
            "name": name,
        }

    try:
        import requests

        headers = {
            "pinata_api_key": IPFS_API_KEY,
            "pinata_secret_api_key": IPFS_API_SECRET,
        }
        payload = {
            "pinataMetadata": {"name": name},
            "pinataContent": content,
        }
        resp = requests.post(
            f"{IPFS_API_URL}/pinning/pinJSONToIPFS",
            json=payload,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        cid = resp.json()["IpfsHash"]
        logger.info("Pinned to IPFS: %s", cid)
        return {"status": "pinned", "cid": cid, "name": name}
    except Exception as exc:
        logger.error("IPFS pin failed: %s", exc)
        return {"status": "error", "error": str(exc)}
