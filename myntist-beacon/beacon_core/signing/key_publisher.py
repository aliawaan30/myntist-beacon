"""
Key publisher — publishes public keys to S3 and/or /.well-known/signing-keys.json.
Stubs gracefully when S3 is not configured.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def publish_key(key_data: Dict[str, Any]) -> bool:
    """
    Publish the public key to S3.

    Returns:
        True if published, False if stubbed.
    """
    if not S3_BUCKET:
        logger.warning("S3_BUCKET not set — key publish skipped (stub)")
        return False

    try:
        import boto3
        client = boto3.client("s3", region_name=AWS_REGION)
        body = json.dumps(key_data, indent=2).encode()
        client.put_object(
            Bucket=S3_BUCKET,
            Key=".well-known/signing-keys.json",
            Body=body,
            ContentType="application/json",
        )
        logger.info("Published signing key to s3://%s/.well-known/signing-keys.json", S3_BUCKET)
        return True
    except Exception as exc:
        logger.error("Key publish failed: %s", exc)
        return False
