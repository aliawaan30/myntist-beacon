"""
Write audit entry — CI/CD deploy hook.

Usage:
  python scripts/write_audit_entry.py \
    --identity deploy-bot \
    --event deploy \
    --action "Phase 2 deployed to production"

Writes a signed audit entry to the IAM substrate audit log.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.getenv("DATABASE_URL", "")


def main():
    parser = argparse.ArgumentParser(description="Write a CI/CD audit entry")
    parser.add_argument("--identity", default="ci-deploy-bot", help="Identity ID")
    parser.add_argument("--event", default="deploy", help="Event type")
    parser.add_argument("--action", default="Deployment completed", help="Action description")
    parser.add_argument("--s-before", type=float, default=None)
    parser.add_argument("--s-after", type=float, default=None)
    args = parser.parse_args()

    if not DATABASE_URL:
        print("WARNING: DATABASE_URL not set — audit entry not persisted")
        print(f"  identity={args.identity}, event={args.event}, action={args.action}")
        return 0

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from iam_substrate.ledger.audit_log import append_audit_entry

        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        Session = sessionmaker(bind=engine)
        db = Session()

        entry = append_audit_entry(
            db=db,
            identity_id=args.identity,
            event_type=args.event,
            action=args.action,
            S_before=args.s_before,
            S_after=args.s_after,
        )
        db.close()
        print(f"Audit entry written: id={entry.id}, hash={entry.hash[:16]}...")
        return 0
    except Exception as exc:
        print(f"ERROR: Failed to write audit entry: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
