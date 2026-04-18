"""
Lens Protocol adapter — stub implementation.

Posts beacon pulse to Lens. Skips actual API call if credentials not set.
Includes rate limit check via DynamoDB (stubs to in-memory counter if not configured).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

LENS_PROFILE_ID = os.getenv("LENS_PROFILE_ID", "")
LENS_ACCESS_TOKEN = os.getenv("LENS_ACCESS_TOKEN", "")

_in_memory_rate_limit: Dict[str, int] = {}
RATE_LIMIT_WINDOW_SECONDS = 3600
RATE_LIMIT_MAX = 10


def _check_rate_limit(key: str) -> bool:
    """
    Check rate limit via DynamoDB (stubs to in-memory if not configured).
    Returns True if within limit, False if exceeded.
    """
    now = int(time.time())
    window_key = f"{key}:{now // RATE_LIMIT_WINDOW_SECONDS}"

    aws_region = os.getenv("AWS_REGION", "us-east-1")
    dynamodb_table = os.getenv("DYNAMODB_RATE_TABLE", "")

    if dynamodb_table:
        try:
            import boto3
            client = boto3.client("dynamodb", region_name=aws_region)
            response = client.update_item(
                TableName=dynamodb_table,
                Key={"pk": {"S": window_key}},
                UpdateExpression="ADD #cnt :one",
                ExpressionAttributeNames={"#cnt": "count"},
                ExpressionAttributeValues={":one": {"N": "1"}},
                ReturnValues="UPDATED_NEW",
            )
            count = int(response["Attributes"]["count"]["N"])
            return count <= RATE_LIMIT_MAX
        except Exception as exc:
            logger.warning("DynamoDB rate limit check failed, using in-memory: %s", exc)

    count = _in_memory_rate_limit.get(window_key, 0) + 1
    _in_memory_rate_limit[window_key] = count
    return count <= RATE_LIMIT_MAX


def post_pulse(content: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Post a beacon pulse update to Lens Protocol.

    Returns:
        Result dict with status and any IDs.
    """
    if not _check_rate_limit("lens"):
        logger.warning("Lens rate limit exceeded — post skipped")
        return {"status": "rate_limited", "platform": "lens"}

    if not LENS_PROFILE_ID or not LENS_ACCESS_TOKEN:
        logger.info("Lens credentials not set — skipping post (stub). Content: %s", content)
        return {"status": "stub", "platform": "lens", "content": content}

    logger.info("Lens post (stub): %s", content)
    return {
        "status": "stub",
        "platform": "lens",
        "profile_id": LENS_PROFILE_ID,
        "content": content,
    }
