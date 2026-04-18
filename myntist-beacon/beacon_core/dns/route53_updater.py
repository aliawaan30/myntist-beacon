"""
route53_updater.py

AWS Route 53 DNS updater — writes 4 TXT records for Myntist beacon anchoring.

Records (all under myntist.com):
  _s.v1         : s={S};dS={delta_S};tau={tau};Q={Q};ts={unix_ts}
  _buoy.latest  : url=https://myntist.com/api/field/v1/status.json;hash={payload_hash}
  _ledger.anchor: ipfs={CID};zenodo=doi:{DOI}  (skipped if unavailable)
  _float.audit  : stub=true

Requires: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
          and IAM permission route53:ChangeResourceRecordSets on the hosted zone.

Skips silently if credentials are not present.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

DOMAIN = os.getenv("GODADDY_DOMAIN", "myntist.com")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
_HOSTED_ZONE_ID = os.getenv("ROUTE53_HOSTED_ZONE_ID", "")


def _get_hosted_zone_id(r53_client) -> Optional[str]:
    """Look up the hosted zone ID for DOMAIN, or use the env override."""
    if _HOSTED_ZONE_ID:
        return _HOSTED_ZONE_ID
    try:
        resp = r53_client.list_hosted_zones_by_name(DNSName=DOMAIN, MaxItems="5")
        for zone in resp.get("HostedZones", []):
            if zone["Name"].rstrip(".") == DOMAIN:
                return zone["Id"].split("/")[-1]
        logger.error("No Route 53 hosted zone found for %s", DOMAIN)
        return None
    except Exception as exc:
        logger.error("Route 53 zone lookup failed: %s", exc)
        return None


def _upsert_txt(r53_client, zone_id: str, name: str, value: str) -> bool:
    """Upsert a single TXT record."""
    fqdn = f"{name}.{DOMAIN}."
    try:
        r53_client.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": fqdn,
                            "Type": "TXT",
                            "TTL": 300,
                            "ResourceRecords": [{"Value": f'"{value}"'}],
                        },
                    }
                ]
            },
        )
        logger.info("Route 53 UPSERT %s = %s", fqdn, value)
        return True
    except Exception as exc:
        logger.error("Route 53 update failed for %s: %s", fqdn, exc)
        return False


def update_dns_records(
    S: float,
    delta_S: float,
    tau: float,
    Q: float,
    payload_hash: str,
    cid: Optional[str] = None,
    doi: Optional[str] = None,
) -> dict:
    """
    Upsert all beacon TXT records in Route 53.

    Returns dict of record_name → success (bool).
    """
    stub = {"_s.v1": False, "_buoy.latest": False, "_ledger.anchor": False, "_float.audit": False}

    try:
        import boto3
        r53 = boto3.client("route53", region_name=AWS_REGION)
    except Exception as exc:
        logger.warning("boto3 unavailable — Route 53 update skipped: %s", exc)
        return stub

    zone_id = _get_hosted_zone_id(r53)
    if not zone_id:
        return stub

    unix_ts = int(time.time())
    results = {}

    results["_s.v1"] = _upsert_txt(
        r53, zone_id, "_s.v1",
        f"s={S:.4f};dS={delta_S:.4f};tau={tau:.4f};Q={Q:.4f};ts={unix_ts}",
    )
    results["_buoy.latest"] = _upsert_txt(
        r53, zone_id, "_buoy.latest",
        f"url=https://myntist.com/api/field/v1/status.json;hash={payload_hash}",
    )

    if cid and doi:
        results["_ledger.anchor"] = _upsert_txt(
            r53, zone_id, "_ledger.anchor", f"ipfs={cid};zenodo=doi:{doi}"
        )
    else:
        logger.info("_ledger.anchor skipped — CID or DOI not available")
        results["_ledger.anchor"] = False

    results["_float.audit"] = _upsert_txt(r53, zone_id, "_float.audit", "stub=true")

    return results
