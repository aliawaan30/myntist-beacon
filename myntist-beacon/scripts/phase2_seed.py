"""
Phase 2 seed — populate 7+ days of synthetic telemetry in field_telemetry.

Usage:
  cd myntist-beacon
  python scripts/phase2_seed.py

This creates enough history for r_HSCE computation to return a value
instead of None.
"""
from __future__ import annotations

import os
import sys
import math
import random
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL env var is not set")
    sys.exit(1)

from beacon_core.telemetry.telemetry_exporter import TelemetryExporter

exporter = TelemetryExporter(DATABASE_URL)

if not exporter._initialized:
    print("ERROR: TelemetryExporter failed to initialise — check DATABASE_URL")
    sys.exit(1)

now = datetime.now(timezone.utc)
DAYS = 8
RECORDS_PER_DAY = 12

print(f"Seeding {DAYS * RECORDS_PER_DAY} Phase 2 telemetry records...")

for day_offset in range(DAYS, -1, -1):
    for hour_offset in range(RECORDS_PER_DAY):
        ts = now - timedelta(days=day_offset, hours=hour_offset * 2)
        t = day_offset / DAYS
        S = round(0.85 + 0.10 * math.cos(t * math.pi) + random.gauss(0, 0.02), 4)
        S = max(0.0, min(1.0, S))
        delta_S = round(random.gauss(0.005, 0.01), 6)
        Q = round(1.0 + random.gauss(0, 0.1), 4)
        Q = max(0.1, Q)
        tau = round(0.85 + random.gauss(0, 0.05), 4)
        tau = max(0.0, min(1.0, tau))
        nabla_phi = round(random.gauss(0.0, 0.1), 4)
        field_state = "stable" if S >= 0.85 else ("excitation" if S >= 0.70 else "incident")

        float_yield = delta_S / 500.0 * 86400
        liquidity_signal = delta_S / (Q * 600) if Q > 0 else 0.0
        coherence_signal = 0.05 + random.gauss(0, 0.02)
        r_HSCE = 0.012 + random.gauss(0, 0.003) if day_offset < DAYS else None

        exporter.insert_field_telemetry({
            "time": ts,
            "identity_id": f"seed_identity_{day_offset % 3 + 1}",
            "S": S,
            "delta_S": delta_S,
            "Q": Q,
            "tau": tau,
            "nabla_phi": nabla_phi,
            "field_state": field_state,
            "float_yield": float_yield,
            "liquidity_signal": liquidity_signal,
            "coherence_signal": coherence_signal,
            "r_HSCE": r_HSCE,
            "float_reinvestment_rate": 0.63,
            "schema_version": "2.0",
        })

print(f"Phase 2 seed complete: {DAYS * RECORDS_PER_DAY + RECORDS_PER_DAY} records inserted.")
print("r_HSCE will now be computable via TelemetryExporter.get_s_n_days_ago(7).")
