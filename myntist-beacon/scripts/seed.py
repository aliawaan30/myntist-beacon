"""
Seed script — creates 3 test identities with varied S scores.

Usage:
  python scripts/seed.py
"""
from __future__ import annotations

import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.example"))

from iam_substrate.substrate_api.database import get_session_local, init_db
from iam_substrate.substrate_api.models import Identity, TelemetryRecord
from iam_substrate.substrate_api.telemetry_emitter import emit_telemetry
from beacon_core.telemetry.survivability_engine import SurvivabilityEngine


IDENTITIES = [
    {
        "id": "identity_1",
        "display_name": "Alpha Node",
        "Q": 1.0,
        "nabla_phi": 0.0,
        "tau": 0.95,
    },
    {
        "id": "identity_2",
        "display_name": "Beta Node",
        "Q": 1.2,
        "nabla_phi": 0.3,
        "tau": 0.80,
    },
    {
        "id": "identity_3",
        "display_name": "Gamma Node (stressed)",
        "Q": 1.8,
        "nabla_phi": 0.8,
        "tau": 0.65,
    },
]


def main() -> None:
    print("Initializing database...")
    init_db()

    db = get_session_local()()
    engine = SurvivabilityEngine()

    try:
        for spec in IDENTITIES:
            result = engine.compute(spec["Q"], spec["nabla_phi"], spec["tau"])

            existing = db.query(Identity).filter(Identity.id == spec["id"]).first()
            if existing:
                existing.S = result.S
                existing.Q = spec["Q"]
                existing.tau = spec["tau"]
                existing.nabla_phi = spec["nabla_phi"]
                existing.delta_S = result.delta_S
                existing.field_state = result.field_state
                existing.display_name = spec["display_name"]
                print(f"  Updated: {spec['id']} | S={result.S:.4f} | {result.field_state}")
            else:
                identity = Identity(
                    id=spec["id"],
                    display_name=spec["display_name"],
                    S=result.S,
                    Q=spec["Q"],
                    tau=spec["tau"],
                    nabla_phi=spec["nabla_phi"],
                    delta_S=result.delta_S,
                    field_state=result.field_state,
                )
                db.add(identity)
                print(f"  Created: {spec['id']} | S={result.S:.4f} | {result.field_state}")

            db.commit()

            emit_telemetry(
                db=db,
                identity_id=spec["id"],
                S=result.S,
                delta_S=result.delta_S,
                Q=spec["Q"],
                tau=spec["tau"],
                nabla_phi=spec["nabla_phi"],
                field_state=result.field_state,
            )

        print("\nSeed complete. 3 identities populated:")
        identities = db.query(Identity).all()
        for i in identities:
            print(f"  {i.id}: S={i.S:.4f} field_state={i.field_state}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
