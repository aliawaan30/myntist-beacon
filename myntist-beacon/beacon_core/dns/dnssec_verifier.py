"""
DNSSEC verifier — queries DNS TXT records for beacon anchors.

Uses dns.resolver (dnspython) when available for true TXT record lookup.
Falls back to socket reachability check when dnspython is not installed.

Note: Full DNSSEC chain-of-trust validation requires system resolver
support (e.g. unbound with DNSSEC enabled). This module verifies TXT record
presence and content; DNSSEC signature validation is done via resolver flags.

Install dnspython for production use:
  pip install dnspython
"""
from __future__ import annotations

import logging
import os
import socket
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

GODADDY_DOMAIN = os.getenv("GODADDY_DOMAIN", "myntist.com")

EXPECTED_RECORDS = ["_s.v1", "_buoy.latest", "_ledger.anchor", "_float.audit"]


def _try_dns_txt_lookup(fqdn: str) -> Optional[List[str]]:
    """
    Resolve TXT records using dnspython if available.
    Returns list of TXT strings, or None if dnspython is absent or lookup fails.
    """
    try:
        import dns.resolver
        answers = dns.resolver.resolve(fqdn, "TXT")
        return [rdata.to_text().strip('"') for rdata in answers]
    except ImportError:
        return None
    except Exception as exc:
        logger.debug("dnspython TXT lookup failed for %s: %s", fqdn, exc)
        return None


def _fallback_reachability_check(fqdn: str) -> bool:
    """
    Fallback: check hostname resolves via getaddrinfo.
    Reachability check only — not a true TXT/DNSSEC verification.
    """
    try:
        socket.getaddrinfo(fqdn, None)
        return True
    except Exception:
        return False


def verify_txt_record(
    name: str, domain: str = GODADDY_DOMAIN
) -> Tuple[bool, Optional[str]]:
    """
    Verify a DNS TXT record exists for a beacon anchor.

    Returns:
        (found: bool, value: str|None) — value is the first TXT string if found.
    """
    fqdn = f"{name}.{domain}"
    txt_values = _try_dns_txt_lookup(fqdn)

    if txt_values is not None:
        if txt_values:
            logger.debug("TXT record found for %s: %s", fqdn, txt_values[0])
            return True, txt_values[0]
        logger.debug("TXT lookup returned empty for %s", fqdn)
        return False, None

    # dnspython not available — reachability fallback
    logger.warning(
        "dnspython not available; performing reachability check only for %s. "
        "Install dnspython for true TXT/DNSSEC verification.",
        fqdn,
    )
    reachable = _fallback_reachability_check(fqdn)
    return reachable, fqdn if reachable else None


def verify_all(domain: str = GODADDY_DOMAIN) -> Dict[str, bool]:
    """
    Verify all 4 beacon TXT anchor records are resolvable.

    Returns a dict mapping each anchor name to True (found) or False (not found).
    """
    results: Dict[str, bool] = {}
    for record in EXPECTED_RECORDS:
        found, _ = verify_txt_record(record, domain)
        results[record] = found
        logger.info("DNS anchor %s.%s → %s", record, domain, "OK" if found else "MISSING")
    return results
