"""
Farcaster adapter — stub implementation.

Posts beacon pulse to Farcaster via hub. Skips actual API call if credentials not set.
Includes rate limit check via DynamoDB (stubs to in-memory counter if not configured).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

FARCASTER_FID = os.getenv("FARCASTER_FID", "")
FARCASTER_HUB_URL = os.getenv("FARCASTER_HUB_URL", "https://hub.farcaster.xyz:2281")
FARCASTER_SIGNER_UUID = os.getenv("FARCASTER_SIGNER_UUID", "")

_in_memory_rate_limit: Dict[str, int] = {}
RATE_LIMIT_WINDOW_SECONDS = 3600
RATE_LIMIT_MAX = 10


def _check_rate_limit(key: str) -> bool:
    now = int(time.time())
    window_key = f"{key}:{now // RATE_LIMIT_WINDOW_SECONDS}"
    count = _in_memory_rate_limit.get(window_key, 0) + 1
    _in_memory_rate_limit[window_key] = count
    return count <= RATE_LIMIT_MAX


def cast(content: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Cast a message to Farcaster.

    Returns:
        Result dict with status and any IDs.
    """
    if not _check_rate_limit("farcaster"):
        logger.warning("Farcaster rate limit exceeded — cast skipped")
        return {"status": "rate_limited", "platform": "farcaster"}

    if not FARCASTER_FID or not FARCASTER_SIGNER_UUID:
        logger.info(
            "Farcaster credentials not set — skipping cast (stub). Content: %s", content
        )
        return {"status": "stub", "platform": "farcaster", "content": content}

    logger.info("Farcaster cast (stub): hub=%s fid=%s content=%s", FARCASTER_HUB_URL, FARCASTER_FID, content)
    return {
        "status": "stub",
        "platform": "farcaster",
        "fid": FARCASTER_FID,
        "hub": FARCASTER_HUB_URL,
        "content": content,
    }
