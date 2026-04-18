"""
Zenodo client — stub implementation.

Deposits records to Zenodo. Returns mock DOI if credentials not set.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ZENODO_API_KEY = os.getenv("ZENODO_API_KEY", "")
ZENODO_SANDBOX = os.getenv("ZENODO_SANDBOX", "true").lower() == "true"

ZENODO_BASE_URL = (
    "https://sandbox.zenodo.org/api" if ZENODO_SANDBOX else "https://zenodo.org/api"
)


def deposit(
    title: str,
    description: str,
    file_content: bytes,
    file_name: str = "payload.json",
) -> Dict[str, Any]:
    """
    Create a Zenodo deposit.

    Returns:
        dict with doi, deposit_id, status
    """
    if not ZENODO_API_KEY:
        logger.info("ZENODO_API_KEY not set — returning mock deposit (stub)")
        return {
            "status": "stub",
            # Stub: set ZENODO_API_KEY for real Zenodo deposits
            "doi": "10.5281/zenodo.mock-000001",
            "deposit_id": "mock-000001",
            "title": title,
        }

    try:
        import requests

        headers = {"Authorization": f"Bearer {ZENODO_API_KEY}"}

        deposit_resp = requests.post(
            f"{ZENODO_BASE_URL}/deposit/depositions",
            headers=headers,
            json={},
            timeout=30,
        )
        deposit_resp.raise_for_status()
        deposition_id = deposit_resp.json()["id"]

        requests.post(
            f"{ZENODO_BASE_URL}/deposit/depositions/{deposition_id}/files",
            headers=headers,
            data={"name": file_name},
            files={"file": (file_name, file_content)},
            timeout=60,
        ).raise_for_status()

        requests.put(
            f"{ZENODO_BASE_URL}/deposit/depositions/{deposition_id}",
            headers=headers,
            json={
                "metadata": {
                    "title": title,
                    "upload_type": "dataset",
                    "description": description,
                    "creators": [{"name": "Myntist Beacon"}],
                }
            },
            timeout=30,
        ).raise_for_status()

        pub_resp = requests.post(
            f"{ZENODO_BASE_URL}/deposit/depositions/{deposition_id}/actions/publish",
            headers=headers,
            timeout=30,
        )
        pub_resp.raise_for_status()
        doi = pub_resp.json().get("doi", f"10.5281/zenodo.{deposition_id}")
        return {"status": "published", "doi": doi, "deposit_id": deposition_id}
    except Exception as exc:
        logger.error("Zenodo deposit failed: %s", exc)
        return {"status": "error", "error": str(exc)}
