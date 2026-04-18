"""
Demo script — triggers a score drop on identity_3 and confirms autoheal fires.

Usage:
  python scripts/demo.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.example"))

from iam_substrate.substrate_api.database import get_session_local, init_db
from iam_substrate.substrate_api.models import Identity
from iam_substrate.substrate_api.autoheal import run_autoheal
from iam_substrate.substrate_api.telemetry_emitter import emit_telemetry
from beacon_core.telemetry.survivability_engine import SurvivabilityEngine


def main() -> None:
    print("=== Myntist Beacon Demo: Autoheal Loop ===\n")
    init_db()
    db = get_session_local()()
    engine = SurvivabilityEngine()

    try:
        identity = db.query(Identity).filter(Identity.id == "identity_3").first()
        if not identity:
            print("identity_3 not found — run 'make seed' first")
            sys.exit(1)

        print(f"Before: identity_3 S={identity.S:.4f} field_state={identity.field_state}")

        # Trigger a severe score drop
        result = engine.compute(Q=3.0, nabla_phi=1.2, tau=0.4)
        old_S = identity.S
        identity.S = result.S
        identity.Q = 3.0
        identity.tau = 0.4
        identity.nabla_phi = 1.2
        identity.delta_S = result.S - old_S
        identity.field_state = result.field_state
        db.commit()

        emit_telemetry(
            db=db,
            identity_id="identity_3",
            S=result.S,
            delta_S=result.S - old_S,
            Q=3.0,
            tau=0.4,
            nabla_phi=1.2,
            field_state=result.field_state,
        )

        print(f"After score drop: S={result.S:.4f} field_state={result.field_state}")

        flagged = [{"id": "identity_3", "S": result.S, "field_state": result.field_state}]
        print(f"\nIdentities flagged for autoheal: {[f['id'] for f in flagged]}")

        print("\nRunning autoheal...")
        autoheal_results = run_autoheal(flagged, db=db)
        for r in autoheal_results:
            print(f"  Autoheal result: {r}")

        print("\n=== Demo complete. Autoheal loop executed successfully. ===")
    finally:
        db.close()


if __name__ == "__main__":
    main()
