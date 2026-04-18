"""
Autoheal — remediates identities with S < 0.7.

Actions:
  - Open GitHub PR via PyGithub (if GH_APP_ID, GH_APP_INSTALLATION_ID, GH_APP_REPO are set)
  - Post Slack alert (if SLACK_WEBHOOK_URL is set)
  - Always log to audit_log
"""
from __future__ import annotations

import json
import logging
import os
import time as _time
from typing import List, Any

import requests

logger = logging.getLogger(__name__)

GH_APP_ID = os.getenv("GH_APP_ID", "")
GH_APP_PRIVATE_KEY = os.getenv("GH_APP_PRIVATE_KEY", "")
GH_APP_REPO = os.getenv("GH_APP_REPO", "")
GH_APP_INSTALLATION_ID = os.getenv("GH_APP_INSTALLATION_ID", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#myntist-beacon-alerts")


def _open_github_pr(identity: Any) -> str:
    """
    Open a GitHub remediation PR via PyGithub.

    Required env vars:
      GH_APP_ID              — GitHub App numeric ID
      GH_APP_PRIVATE_KEY     — GitHub App private key (PEM)
      GH_APP_INSTALLATION_ID — Installation ID for the GitHub App on the target repo
      GH_APP_REPO            — Target repository in "org/repo" format

    Flow:
      1. Authenticate as the GitHub App installation
      2. Create a branch  autoheal/<identity_id>-<unix_ts>
      3. Commit a remediation JSON record to that branch
      4. Open a PR against the repo default branch
    """
    if not GH_APP_REPO or not GH_APP_INSTALLATION_ID:
        logger.warning(
            "GitHub PR skipped: GH_APP_REPO or GH_APP_INSTALLATION_ID not set "
            "(identity=%s)", identity.get("id"),
        )
        return "skipped (GH_APP_REPO / GH_APP_INSTALLATION_ID not configured)"

    try:
        from github import GithubIntegration, Auth

        auth = Auth.AppAuth(int(GH_APP_ID), GH_APP_PRIVATE_KEY)
        gi = GithubIntegration(auth=auth)
        installation = gi.get_installation(int(GH_APP_INSTALLATION_ID))
        gh = installation.get_github_for_installation()

        repo = gh.get_repo(GH_APP_REPO)
        default_branch = repo.default_branch
        base_sha = repo.get_git_ref(f"heads/{default_branch}").object.sha

        identity_id = identity.get("id", "unknown")
        ts = int(_time.time())
        branch_name = f"autoheal/{identity_id}-{ts}"

        repo.create_git_ref(f"refs/heads/{branch_name}", base_sha)

        remediation_record = {
            "identity_id": identity_id,
            "S": identity.get("S"),
            "field_state": identity.get("field_state", "incident"),
            "triggered_at": ts,
            "action": "autoheal_remediation",
        }

        repo.create_file(
            path=f"autoheal/{identity_id}-{ts}.json",
            message=f"autoheal: remediation record for {identity_id}",
            content=json.dumps(remediation_record, indent=2),
            branch=branch_name,
        )

        pr = repo.create_pull(
            title=f"Autoheal: Remediate {identity_id} (S={identity.get('S', 0):.3f})",
            body=(
                f"## Autoheal Triggered\n\n"
                f"**Identity:** `{identity_id}`  \n"
                f"**Survivability Score:** {identity.get('S', 0):.4f}  \n"
                f"**Field State:** `{identity.get('field_state', 'incident')}`  \n"
                f"**Triggered at:** {ts}  \n\n"
                f"This PR was opened automatically by the autoheal system because the "
                f"survivability score dropped below the remediation threshold (0.7). "
                f"Review the remediation record and merge once the field state is verified stable."
            ),
            head=branch_name,
            base=default_branch,
        )

        logger.info(
            "GitHub PR #%d opened for identity %s (S=%.3f): %s",
            pr.number, identity_id, identity.get("S", 0), pr.html_url,
        )
        return f"opened: {pr.html_url}"

    except Exception as exc:
        logger.warning("GitHub PR creation failed for identity %s: %s", identity.get("id"), exc)
        return f"failed: {exc}"


def _post_slack_alert(identity: Any) -> None:
    """Post a Slack alert about a flagged identity."""
    if not SLACK_WEBHOOK_URL:
        logger.info(
            "Slack alert skipped (no SLACK_WEBHOOK_URL): identity=%s S=%.3f",
            identity.get("id"),
            identity.get("S", 0),
        )
        return
    try:
        payload = {
            "channel": SLACK_CHANNEL,
            "text": (
                f":warning: *Autoheal Triggered*\n"
                f"Identity `{identity.get('id')}` scored S={identity.get('S', 0):.3f} "
                f"(field_state={identity.get('field_state', 'incident')}). "
                "Remediation initiated."
            ),
        }
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
        resp.raise_for_status()
        logger.info("Slack alert sent for identity %s", identity.get("id"))
    except Exception as exc:
        logger.warning("Slack alert failed: %s", exc)


def run_autoheal(flagged_identities: List[dict], db=None) -> List[dict]:
    """
    Process flagged identities.

    Args:
        flagged_identities: list of dicts with keys: id, S, field_state
        db: optional SQLAlchemy session for audit logging

    Returns:
        list of remediation payloads
    """
    results = []
    for identity in flagged_identities:
        payload = {
            "identity_id": identity.get("id"),
            "S": identity.get("S"),
            "field_state": identity.get("field_state", "incident"),
            "action": "autoheal_triggered",
        }

        if GH_APP_ID:
            pr_result = _open_github_pr(identity)
            payload["github_pr"] = pr_result
        else:
            payload["github_pr"] = "skipped (no GH_APP_ID)"

        _post_slack_alert(identity)
        payload["slack_alert"] = "sent" if SLACK_WEBHOOK_URL else "skipped"

        if db is not None:
            from iam_substrate.ledger.audit_log import append_audit_entry
            try:
                append_audit_entry(
                    db=db,
                    identity_id=identity.get("id", "unknown"),
                    event_type="autoheal",
                    action=json.dumps(payload),
                    S_before=identity.get("S"),
                    S_after=identity.get("S"),
                )
            except Exception as exc:
                logger.warning("Failed to write autoheal audit entry: %s", exc)

        logger.info("Autoheal processed: %s", payload)
        results.append(payload)

    return results
