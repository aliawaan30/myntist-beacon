"""
Tests for the FastAPI substrate API endpoints.
Uses SQLite file-based DB for isolation (no PostgreSQL required).
HMAC signatures are computed using the default dev secret.
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
from unittest.mock import patch

# Use a temp file so it persists across connections in the same test session
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.name}"
os.environ.setdefault("SUBSTRATE_HMAC_SECRET", "dev_secret_67890")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import iam_substrate.substrate_api.database as db_mod

_TEST_ENGINE = create_engine(
    f"sqlite:///{_TMP_DB.name}",
    connect_args={"check_same_thread": False},
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_TEST_ENGINE)

db_mod._engine = _TEST_ENGINE
db_mod._SessionLocal = _TestSession

_HMAC_SECRET = os.environ["SUBSTRATE_HMAC_SECRET"]


def _signed_post(client, path: str, payload: dict):
    """POST with HMAC-signed body."""
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(_HMAC_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        path,
        content=body,
        headers={"Content-Type": "application/json", "X-Substrate-Signature": sig},
    )


@pytest.fixture(scope="module")
def client():
    with patch("iam_substrate.substrate_api.role_decay.start_scheduler"), \
         patch("iam_substrate.substrate_api.role_decay.stop_scheduler"):

        from iam_substrate.substrate_api.models import Base
        Base.metadata.create_all(bind=_TEST_ENGINE)

        from iam_substrate.substrate_api.main import app
        from iam_substrate.substrate_api.database import get_db

        def override_db():
            db = _TestSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db

        with TestClient(app) as c:
            yield c

        app.dependency_overrides.clear()


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_response_structure(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "status" in data
        assert "timestamp" in data
        assert "version" in data
        assert data["status"] == "ok"


class TestEventsEndpoint:
    def test_events_returns_201(self, client):
        # role_change is not in P001's applies_to list so it always passes policy gate
        payload = {
            "identity_id": "test-001",
            "event_type": "role_change",
            "Q": 1.0,
            "nabla_phi": 0.0,
            "tau": 1.0,
        }
        resp = _signed_post(client, "/events", payload)
        assert resp.status_code == 201

    def test_events_response_has_S(self, client):
        payload = {
            "identity_id": "test-002",
            "event_type": "role_change",
            "Q": 1.0,
            "nabla_phi": 0.0,
            "tau": 0.9,
        }
        resp = _signed_post(client, "/events", payload)
        assert resp.status_code == 201
        data = resp.json()
        assert "S" in data
        assert "field_state" in data

    def test_events_response_has_policy_fields(self, client):
        """Accepted events include admitted flag and active_policy_ids."""
        payload = {
            "identity_id": "test-policy-ok",
            "event_type": "role_change",
            "Q": 1.0,
            "nabla_phi": 0.0,
            "tau": 1.0,
        }
        resp = _signed_post(client, "/events", payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["admitted"] is True
        assert isinstance(data["active_policy_ids"], list)

    def test_events_token_issued_blocked_by_p001_when_low_liquidity(self, client):
        """
        A fresh identity with delta_S=0 → D=0.0 < 0.10.
        P001 must block token_issued and return 403.
        """
        payload = {
            "identity_id": "test-block-p001",
            "event_type": "token_issued",
            "Q": 1.0,
            "nabla_phi": 0.0,
            "tau": 1.0,
        }
        resp = _signed_post(client, "/events", payload)
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["status"] == "blocked"
        assert "P001" in detail["active_policy_ids"]

    def test_events_rejects_unsigned_request(self, client):
        """Unsigned event should be rejected with 401."""
        resp = client.post("/events", json={
            "identity_id": "test-003",
            "event_type": "token_issued",
            "Q": 1.0,
            "nabla_phi": 0.0,
            "tau": 1.0,
        })
        assert resp.status_code == 401

    def test_events_rejects_tampered_signature(self, client):
        """Tampered HMAC signature should be rejected with 401."""
        resp = client.post(
            "/events",
            json={
                "identity_id": "test-004",
                "event_type": "token_issued",
                "Q": 1.0,
                "nabla_phi": 0.0,
                "tau": 1.0,
            },
            headers={"X-Substrate-Signature": "sha256=deadbeef"},
        )
        assert resp.status_code == 401


class TestScoreEndpoint:
    def test_score_returns_updated_S(self, client):
        payload = {
            "identity_id": "score-test-001",
            "Q": 1.0,
            "nabla_phi": 0.0,
            "tau": 0.9,
        }
        resp = client.post("/score", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "S" in data
        assert "field_state" in data
        assert isinstance(data["S"], float)


class TestTelemetryEndpoints:
    def test_telemetry_latest_returns_required_fields(self, client):
        # Use role_change so the seed event isn't blocked by P001 (token_issued + D < 0.10)
        _signed_post(client, "/events", {
            "identity_id": "telemetry-seed",
            "event_type": "role_change",
            "Q": 1.0,
            "nabla_phi": 0.0,
            "tau": 0.9,
        })
        resp = client.get("/telemetry/latest")
        assert resp.status_code == 200
        data = resp.json()
        required_fields = {"S", "delta_S", "Q", "tau", "nabla_phi", "field_state", "timestamp"}
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_telemetry_historical_returns_list(self, client):
        resp = client.get("/telemetry/historical")
        assert resp.status_code == 200
        data = resp.json()
        assert "records" in data
        assert isinstance(data["records"], list)


class TestValidateEndpoint:
    def test_validate_accepts_valid_bundle(self, client):
        bundle = {
            "identity_id": "test-001",
            "S": 0.9,
            "Q": 1.0,
            "tau": 0.9,
        }
        resp = client.post("/validate", json={"bundle": bundle})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_validate_rejects_invalid_bundle_missing_fields(self, client):
        bundle = {"identity_id": "test-001"}
        resp = client.post("/validate", json={"bundle": bundle})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    def test_validate_rejects_invalid_S_range(self, client):
        bundle = {"identity_id": "t", "S": 2.0, "Q": 1.0, "tau": 0.9}
        resp = client.post("/validate", json={"bundle": bundle})
        assert resp.json()["valid"] is False

    def test_validate_rejects_zero_Q(self, client):
        bundle = {"identity_id": "t", "S": 0.9, "Q": 0.0, "tau": 0.9}
        resp = client.post("/validate", json={"bundle": bundle})
        assert resp.json()["valid"] is False


class TestFieldTelemetryIntegration:
    """
    Integration tests: verify that normal event ingestion writes to field_telemetry
    so that r_HSCE / get_q_variance() reflect live data, not only seeded fixtures.
    """

    def test_event_ingestion_populates_field_telemetry(self, client):
        """After several role_change events, field_telemetry must contain rows."""
        from iam_substrate.substrate_api.main import _exporter

        for i in range(3):
            _signed_post(client, "/events", {
                "identity_id": f"ft-integration-{i}",
                "event_type": "role_change",
                "Q": 1.0 + i * 0.1,
                "nabla_phi": 0.0,
                "tau": 0.9,
            })

        rows = _exporter.get_recent_field_telemetry(days=1)
        assert len(rows) > 0, "field_telemetry must contain at least one row after event ingestion"
        assert rows[0].get("S") is not None, "field_telemetry row must have S column"

    def test_q_variance_non_zero_after_live_ingestion(self, client):
        """
        get_q_variance() must return > 0 once multiple Q values are present
        in field_telemetry, proving DB-backed variance is updated by live events.
        """
        from iam_substrate.substrate_api.main import _exporter

        q_values = [0.5, 0.7, 0.9, 1.1, 1.3, 0.6, 0.8]
        for i, q in enumerate(q_values):
            _signed_post(client, "/events", {
                "identity_id": f"ft-qvar-{i}",
                "event_type": "role_change",
                "Q": q,
                "nabla_phi": 0.0,
                "tau": 0.9,
            })

        variance = _exporter.get_q_variance(cycles=len(q_values))
        assert variance > 0.0, (
            f"get_q_variance() returned {variance} — expected > 0 after ingesting "
            f"diverse Q values {q_values}"
        )

    def test_score_endpoint_populates_field_telemetry(self, client):
        """POST /score must also write to field_telemetry (no policy gate on this path)."""
        from iam_substrate.substrate_api.main import _exporter

        before = len(_exporter.get_recent_field_telemetry(days=1))

        client.post("/score", json={
            "identity_id": "ft-score-test",
            "Q": 1.2,
            "nabla_phi": 0.1,
            "tau": 0.85,
        })

        after = len(_exporter.get_recent_field_telemetry(days=1))
        assert after > before, "field_telemetry row count must increase after POST /score"
