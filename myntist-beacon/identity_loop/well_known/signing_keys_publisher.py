"""
Signing keys publisher — publishes current signing keys to /.well-known/signing-keys.json.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
CLOUDFRONT_DOMAIN = os.getenv("CLOUDFRONT_DOMAIN", "https://myntist.com")


def publish_signing_keys(key_states: list) -> bool:
    """
    Publish the current signing keys manifest.

    Args:
        key_states: list of KeyState dicts

    Returns:
        True if published, False if stubbed.
    """
    payload: Dict[str, Any] = {
        "keys": [
            {
                "version": ks.get("version") if isinstance(ks, dict) else ks.version,
                "public_key": ks.get("public_key") if isinstance(ks, dict) else ks.public_key,
                "threshold_m": ks.get("threshold_m") if isinstance(ks, dict) else ks.threshold_m,
                "threshold_n": ks.get("threshold_n") if isinstance(ks, dict) else ks.threshold_n,
            }
            for ks in key_states
        ],
        "endpoint": f"{CLOUDFRONT_DOMAIN}/.well-known/signing-keys.json",
    }

    if not S3_BUCKET:
        logger.warning("S3_BUCKET not set — signing keys publish skipped (stub)")
        logger.info("Signing keys payload: %s", json.dumps(payload))
        return False

    try:
        import boto3
        client = boto3.client("s3", region_name=AWS_REGION)
        client.put_object(
            Bucket=S3_BUCKET,
            Key=".well-known/signing-keys.json",
            Body=json.dumps(payload, indent=2).encode(),
            ContentType="application/json",
        )
        logger.info("Signing keys published to s3://%s/.well-known/signing-keys.json", S3_BUCKET)
        return True
    except Exception as exc:
        logger.error("Signing keys publish failed: %s", exc)
        return False
