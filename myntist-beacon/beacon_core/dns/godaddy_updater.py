"""
GoDaddy DNS updater — updates 4 TXT records for Myntist beacon anchoring.

Records:
  _s.v1         : s={S};dS={delta_S};tau={tau};Q={Q};ts={unix_ts}
  _buoy.latest  : url=<canonical status.json URL>;hash={payload_hash}
  _ledger.anchor: ipfs={CID};zenodo=doi:{DOI}  (written only when CID and DOI are provided)
  _float.audit  : fy={float_yield};frr={float_reinvestment_rate};cs={coherence_signal};ts={unix_ts}

Skips all updates if GODADDY_API_KEY is not set.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GODADDY_API_KEY = os.getenv("GODADDY_API_KEY", "")
GODADDY_API_SECRET = os.getenv("GODADDY_API_SECRET", "")
GODADDY_DOMAIN = os.getenv("GODADDY_DOMAIN", "myntist.com")
GODADDY_API_BASE = "https://api.godaddy.com/v1"

_CANONICAL_URL = os.getenv("CANONICAL_URL", "")
_CLOUDFRONT_DOMAIN = os.getenv("CLOUDFRONT_DOMAIN", f"https://{GODADDY_DOMAIN}")


def _status_json_url() -> str:
    """Return the canonical status.json URL, respecting env var overrides."""
    if _CANONICAL_URL:
        return _CANONICAL_URL
    return f"{_CLOUDFRONT_DOMAIN}/api/field/v1/status.json"


def _update_txt_record(name: str, value: str) -> bool:
    """Update a single TXT DNS record via GoDaddy API."""
    headers = {
        "Authorization": f"sso-key {GODADDY_API_KEY}:{GODADDY_API_SECRET}",
        "Content-Type": "application/json",
    }
    url = f"{GODADDY_API_BASE}/domains/{GODADDY_DOMAIN}/records/TXT/{name}"
    payload = [{"data": value, "ttl": 600}]
    try:
        resp = requests.put(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        logger.info("Updated DNS TXT %s.%s = %s", name, GODADDY_DOMAIN, value)
        return True
    except Exception as exc:
        logger.error("GoDaddy DNS update failed for %s: %s", name, exc)
        return False


def update_dns_records(
    S: float,
    delta_S: float,
    tau: float,
    Q: float,
    payload_hash: str,
    cid: Optional[str] = None,
    doi: Optional[str] = None,
    float_yield: Optional[float] = None,
    float_reinvestment_rate: Optional[float] = None,
    coherence_signal: Optional[float] = None,
) -> dict:
    """
    Update all 4 TXT records.

    Args:
        S, delta_S, tau, Q: survivability telemetry values
        payload_hash:       SHA-256 of the current status.json payload
        cid:                IPFS CID of the anchored payload (optional)
        doi:                Zenodo DOI of the deposit (optional)
        float_yield:        current float yield from FinancialEngine (optional)
        float_reinvestment_rate: float reinvestment rate (optional)
        coherence_signal:   coherence signal from FinancialEngine (optional)

    Returns:
        dict of record_name → success (bool)
    """
    if not GODADDY_API_KEY:
        logger.warning("GODADDY_API_KEY not set — DNS update skipped")
        return {
            "_s.v1": False,
            "_buoy.latest": False,
            "_ledger.anchor": False,
            "_float.audit": False,
        }

    unix_ts = int(time.time())
    results = {}

    results["_s.v1"] = _update_txt_record(
        "_s.v1",
        f"s={S:.4f};dS={delta_S:.4f};tau={tau:.4f};Q={Q:.4f};ts={unix_ts}",
    )

    results["_buoy.latest"] = _update_txt_record(
        "_buoy.latest",
        f"url={_status_json_url()};hash={payload_hash}",
    )

    if cid and doi:
        results["_ledger.anchor"] = _update_txt_record(
            "_ledger.anchor",
            f"ipfs={cid};zenodo=doi:{doi}",
        )
    else:
        logger.info("_ledger.anchor skipped — CID or DOI not available")
        results["_ledger.anchor"] = False

    float_parts = [f"ts={unix_ts}"]
    if float_yield is not None:
        float_parts.append(f"fy={float_yield:.6f}")
    if float_reinvestment_rate is not None:
        float_parts.append(f"frr={float_reinvestment_rate:.6f}")
    if coherence_signal is not None:
        float_parts.append(f"cs={coherence_signal:.6f}")

    results["_float.audit"] = _update_txt_record(
        "_float.audit",
        ";".join(float_parts),
    )

    return results
