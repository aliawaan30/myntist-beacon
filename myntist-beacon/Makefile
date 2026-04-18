.PHONY: dev test seed demo clean phase2-migrate phase2-seed phase2-demo

# NOTE: canonical Python packages are in underscore-named directories.
# Edit:  iam_substrate/  beacon_core/  identity_loop/  kcp/
# The hyphenated dirs (iam-substrate/, beacon-core/, identity-loop/) are legacy
# references only. All runtime imports and uvicorn commands use underscore names.

dev:
	docker compose up --build

test:
	pytest tests/ -v

seed:
	python scripts/seed.py

demo:
	@echo "Running demo: seed identities, trigger score drop on identity_3, verify autoheal..."
	python scripts/seed.py
	python scripts/demo.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.db" -delete 2>/dev/null || true

# ── Phase 2 targets ──────────────────────────────────────────────────────────

phase2-migrate:
	@echo "Running Phase 2 schema migration..."
	@echo "  Creating field_telemetry and iam_temporal_events tables..."
	python -c "\
from beacon_core.telemetry.telemetry_exporter import TelemetryExporter; \
exp = TelemetryExporter(); \
print('  Tables initialised:', exp._initialized)"
	@echo "Phase 2 migration complete."

phase2-seed:
	@echo "Seeding Phase 2 telemetry (8 days of synthetic data)..."
	python scripts/phase2_seed.py

phase2-demo:
	@echo "Running Phase 2 demo..."
	@echo "  Step 1: Phase 2 seed"
	python scripts/phase2_seed.py
	@echo "  Step 2: Financial engine smoke test"
	python -c "\
from beacon_core.telemetry.financial_engine import FinancialEngine; \
eng = FinancialEngine(); \
out = eng.compute_all({'S':0.9,'delta_S':0.01,'Q':1.0,'tau':1.0}); \
print('  float_yield:', out['float_yield']); \
print('  liquidity_signal:', out['liquidity_signal']); \
print('  schema_version:', out['schema_version'])"
	@echo "  Step 3: Policy engine smoke test"
	python -c "\
from iam_substrate.substrate_api.policy_engine import evaluate; \
res = evaluate({'S':0.9,'delta_S':0.0,'Q':1.0,'tau':1.0,'nabla_phi':0.0,'field_state':'stable','D':0.15,'Ttau':0.10}); \
print('  admitted:', res['admitted']); \
print('  active_policies:', res['active_policy_ids'])"
	@echo "Phase 2 demo complete."
