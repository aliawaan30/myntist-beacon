"""
RSS 2.0 generator for Myntist Beacon Pulse.

Max 50 items. Writes to /tmp/rss.xml or S3 if configured.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
CLOUDFRONT_DOMAIN = os.getenv("CLOUDFRONT_DOMAIN", "https://myntist.com")
MAX_ITEMS = 50


def _prettify(elem: Element) -> str:
    raw = tostring(elem, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ")


def generate_rss(items: List[Dict[str, Any]], output_path: str = "/tmp/rss.xml") -> str:
    """
    Generate RSS 2.0 XML from a list of telemetry snapshots.

    Args:
        items: list of dicts with keys: S, delta_S, field_state, timestamp
        output_path: local path to write XML

    Returns:
        Path where the RSS was written.
    """
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")

    SubElement(channel, "title").text = "Myntist Sovereign Beacon"
    SubElement(channel, "link").text = f"{CLOUDFRONT_DOMAIN}/api/field/v1/status.json"
    SubElement(channel, "description").text = "Live beacon pulse feed"
    SubElement(channel, "language").text = "en-us"
    SubElement(channel, "lastBuildDate").text = datetime.now(timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S +0000"
    )

    for item_data in items[:MAX_ITEMS]:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = "Myntist Beacon Pulse"
        SubElement(item, "link").text = f"{CLOUDFRONT_DOMAIN}/api/field/v1/status.json"

        S = item_data.get("S", 0.0)
        delta_S = item_data.get("delta_S", 0.0)
        state = item_data.get("field_state", "unknown")
        SubElement(item, "description").text = (
            f"S={S:.4f} | dS={delta_S:+.4f} | state={state}"
        )

        ts = item_data.get("timestamp", datetime.now(timezone.utc).isoformat())
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts)
            except ValueError:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        SubElement(item, "pubDate").text = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        SubElement(item, "guid").text = f"{CLOUDFRONT_DOMAIN}/pulse/{int(dt.timestamp())}"

    xml_content = _prettify(rss)

    with open(output_path, "w") as f:
        f.write(xml_content)
    logger.info("RSS written to %s", output_path)

    if S3_BUCKET:
        _write_to_s3(xml_content)

    return output_path


def _write_to_s3(content: str) -> None:
    try:
        import boto3
        client = boto3.client("s3", region_name=AWS_REGION)
        client.put_object(
            Bucket=S3_BUCKET,
            Key="feeds/rss.xml",
            Body=content.encode(),
            ContentType="application/rss+xml",
        )
        logger.info("RSS uploaded to s3://%s/feeds/rss.xml", S3_BUCKET)
    except Exception as exc:
        logger.error("RSS S3 upload failed: %s", exc)
