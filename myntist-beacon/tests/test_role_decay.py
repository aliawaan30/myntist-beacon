"""
Tests for iam-substrate/substrate_api/role_decay.py
Uses mocks so no DB connection is needed.
"""
import os
import sys
from unittest.mock import MagicMock, call, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest


def _make_identity(id: str, S: float, field_state: str = "incident", Q: float = 1.0, tau: float = 1.0, nabla_phi: float = 0.0):
    identity = MagicMock()
    identity.id = id
    identity.S = S
    identity.field_state = field_state
    identity.Q = Q
    identity.tau = tau
    identity.nabla_phi = nabla_phi
    return identity


class TestRoleDecay:
    def test_identity_with_low_S_is_flagged(self):
        from iam_substrate.substrate_api.role_decay import get_flagged_identities

        db = MagicMock()
        db.query.return_value.all.return_value = [
            _make_identity("id-001", S=0.5, field_state="incident"),
            _make_identity("id-002", S=0.9, field_state="stable"),
        ]

        flagged = get_flagged_identities(db)
        assert len(flagged) == 1
        assert flagged[0]["id"] == "id-001"

    def test_identity_with_high_S_is_not_flagged(self):
        from iam_substrate.substrate_api.role_decay import get_flagged_identities

        db = MagicMock()
        db.query.return_value.all.return_value = [
            _make_identity("id-001", S=0.9, field_state="stable"),
            _make_identity("id-002", S=0.75, field_state="excitation"),
        ]

        flagged = get_flagged_identities(db)
        assert len(flagged) == 0

    def test_S_exactly_0_7_is_not_flagged(self):
        """S == 0.7 should NOT be flagged (threshold is strictly < 0.7)."""
        from iam_substrate.substrate_api.role_decay import get_flagged_identities

        db = MagicMock()
        db.query.return_value.all.return_value = [
            _make_identity("id-001", S=0.7, field_state="excitation"),
        ]
        flagged = get_flagged_identities(db)
        assert len(flagged) == 0

    def test_S_just_below_0_7_is_flagged(self):
        from iam_substrate.substrate_api.role_decay import get_flagged_identities

        db = MagicMock()
        db.query.return_value.all.return_value = [
            _make_identity("id-001", S=0.699, field_state="incident"),
        ]
        flagged = get_flagged_identities(db)
        assert len(flagged) == 1

    def test_autoheal_called_for_flagged_identities(self):
        """run_autoheal is invoked with the correct identities."""
        from iam_substrate.substrate_api.autoheal import run_autoheal

        flagged = [
            {"id": "id-001", "S": 0.5, "field_state": "incident"},
        ]
        result = run_autoheal(flagged)
        assert len(result) == 1
        assert result[0]["identity_id"] == "id-001"

    def test_autoheal_not_called_when_no_flagged(self):
        """run_autoheal produces empty result when no identities are flagged."""
        from iam_substrate.substrate_api.autoheal import run_autoheal

        result = run_autoheal([])
        assert result == []

    def test_all_identities_below_threshold_are_flagged(self):
        from iam_substrate.substrate_api.role_decay import get_flagged_identities

        db = MagicMock()
        db.query.return_value.all.return_value = [
            _make_identity(f"id-{i:03d}", S=0.3, field_state="incident")
            for i in range(5)
        ]

        flagged = get_flagged_identities(db)
        assert len(flagged) == 5


class TestEmitLiveTelemetry:
    """Tests for the multi-identity live telemetry emitter."""

    def setup_method(self):
        """Reset the round-robin cursor before each test."""
        import iam_substrate.substrate_api.role_decay as rd
        rd._telemetry_cursor = 0

    def _mock_score_result(self, S=0.95, delta_S=0.0, field_state="stable"):
        result = MagicMock()
        result.S = S
        result.delta_S = delta_S
        result.field_state = field_state
        return result

    def _build_db_mock(self, identities, total=None):
        """
        Return a db mock that handles both:
          db.query(Identity).count()                               → total
          db.query(Identity).order_by(...).offset(...).limit(...).all() → identities
        """
        db = MagicMock()
        db.query.return_value.count.return_value = (
            len(identities) if total is None else total
        )
        (
            db.query.return_value
            .order_by.return_value
            .offset.return_value
            .limit.return_value
            .all.return_value
        ) = identities
        return db

    @patch("iam_substrate.substrate_api.telemetry_emitter.emit_telemetry")
    @patch("iam_substrate.substrate_api.scoring.score_from_inputs")
    @patch("iam_substrate.substrate_api.database.get_session_local")
    def test_emits_for_all_identities(self, mock_get_session, mock_score, mock_emit):
        """emit_live_telemetry calls emit_telemetry once per registered identity."""
        from iam_substrate.substrate_api.role_decay import emit_live_telemetry

        identities = [
            _make_identity("id-001", S=0.9, field_state="stable"),
            _make_identity("id-002", S=0.85, field_state="excitation"),
            _make_identity("id-003", S=0.8, field_state="stable"),
        ]
        db = self._build_db_mock(identities)
        mock_get_session.return_value.return_value = db
        mock_score.return_value = self._mock_score_result()

        emit_live_telemetry()

        assert mock_emit.call_count == 3
        emitted_ids = {c.kwargs["identity_id"] for c in mock_emit.call_args_list}
        assert emitted_ids == {"id-001", "id-002", "id-003"}

    @patch("iam_substrate.substrate_api.telemetry_emitter.emit_telemetry")
    @patch("iam_substrate.substrate_api.scoring.score_from_inputs")
    @patch("iam_substrate.substrate_api.database.get_session_local")
    def test_falls_back_to_system_when_no_identities(self, mock_get_session, mock_score, mock_emit):
        """With no identities, a single 'system' record is emitted."""
        from iam_substrate.substrate_api.role_decay import emit_live_telemetry

        db = self._build_db_mock([])
        mock_get_session.return_value.return_value = db
        mock_score.return_value = self._mock_score_result()

        emit_live_telemetry()

        mock_emit.assert_called_once()
        assert mock_emit.call_args.kwargs["identity_id"] == "system"

    @patch("iam_substrate.substrate_api.telemetry_emitter.emit_telemetry")
    @patch("iam_substrate.substrate_api.scoring.score_from_inputs")
    @patch("iam_substrate.substrate_api.database.get_session_local")
    def test_batch_limit_and_offset_are_passed_to_query(self, mock_get_session, mock_score, mock_emit):
        """The query must use .offset() and .limit() for pagination."""
        from iam_substrate.substrate_api import role_decay
        from iam_substrate.substrate_api.role_decay import emit_live_telemetry

        db = self._build_db_mock([_make_identity("id-001", S=0.9)])
        mock_get_session.return_value.return_value = db
        mock_score.return_value = self._mock_score_result()

        emit_live_telemetry()

        db.query.return_value.order_by.return_value.offset.assert_called_once_with(0)
        db.query.return_value.order_by.return_value.offset.return_value.limit.assert_called_once_with(
            role_decay._TELEMETRY_BATCH_LIMIT
        )

    @patch("iam_substrate.substrate_api.telemetry_emitter.emit_telemetry")
    @patch("iam_substrate.substrate_api.scoring.score_from_inputs")
    @patch("iam_substrate.substrate_api.database.get_session_local")
    def test_single_identity_still_works(self, mock_get_session, mock_score, mock_emit):
        """A single identity still produces exactly one telemetry record."""
        from iam_substrate.substrate_api.role_decay import emit_live_telemetry

        db = self._build_db_mock([_make_identity("id-001", S=0.9, field_state="stable")])
        mock_get_session.return_value.return_value = db
        mock_score.return_value = self._mock_score_result()

        emit_live_telemetry()

        mock_emit.assert_called_once()
        assert mock_emit.call_args.kwargs["identity_id"] == "id-001"

    @patch("iam_substrate.substrate_api.telemetry_emitter.emit_telemetry")
    @patch("iam_substrate.substrate_api.scoring.score_from_inputs")
    @patch("iam_substrate.substrate_api.database.get_session_local")
    def test_round_robin_covers_all_identities_across_cycles(self, mock_get_session, mock_score, mock_emit):
        """
        With more identities than _TELEMETRY_BATCH_LIMIT, two consecutive
        emit_live_telemetry() calls must together cover all identities.
        """
        import iam_substrate.substrate_api.role_decay as rd
        from iam_substrate.substrate_api.role_decay import emit_live_telemetry

        batch = rd._TELEMETRY_BATCH_LIMIT
        total = batch + 10  # 60 identities total
        first_batch = [_make_identity(f"id-{i:03d}", S=0.9) for i in range(batch)]
        second_batch = [_make_identity(f"id-{i:03d}", S=0.9) for i in range(batch, total)]

        db1 = self._build_db_mock(first_batch, total=total)
        db2 = self._build_db_mock(second_batch, total=total)
        mock_get_session.return_value.side_effect = [db1, db2]
        mock_score.return_value = self._mock_score_result()

        emit_live_telemetry()  # cycle 1: covers first_batch (0..49)
        emit_live_telemetry()  # cycle 2: covers second_batch (50..59)

        assert mock_emit.call_count == total
        emitted_ids = {c.kwargs["identity_id"] for c in mock_emit.call_args_list}
        expected_ids = {f"id-{i:03d}" for i in range(total)}
        assert emitted_ids == expected_ids

    @patch("iam_substrate.substrate_api.telemetry_emitter.emit_telemetry")
    @patch("iam_substrate.substrate_api.scoring.score_from_inputs")
    @patch("iam_substrate.substrate_api.database.get_session_local")
    def test_exact_multiple_of_batch_has_no_empty_cycle(self, mock_get_session, mock_score, mock_emit):
        """
        When total identities is an exact multiple of _TELEMETRY_BATCH_LIMIT,
        modulo wrapping must ensure no empty no-op cycle is introduced.
        Two consecutive cycles each emit a full batch and cursor wraps to 0.
        """
        import iam_substrate.substrate_api.role_decay as rd
        from iam_substrate.substrate_api.role_decay import emit_live_telemetry

        batch = rd._TELEMETRY_BATCH_LIMIT
        total = batch * 2  # e.g. 100 — exact multiple
        first_batch = [_make_identity(f"id-{i:03d}", S=0.9) for i in range(batch)]
        second_batch = [_make_identity(f"id-{i:03d}", S=0.9) for i in range(batch, total)]

        db1 = self._build_db_mock(first_batch, total=total)
        db2 = self._build_db_mock(second_batch, total=total)
        mock_get_session.return_value.side_effect = [db1, db2]
        mock_score.return_value = self._mock_score_result()

        emit_live_telemetry()  # cycle 1: offset 0, batch identities
        assert rd._telemetry_cursor == batch  # advanced correctly
        assert mock_emit.call_count == batch

        emit_live_telemetry()  # cycle 2: offset batch, batch identities, wraps to 0
        assert rd._telemetry_cursor == 0   # wrapped via modulo, no empty cycle
        assert mock_emit.call_count == total  # all identities covered in 2 cycles

    @patch("iam_substrate.substrate_api.telemetry_emitter.emit_telemetry")
    @patch("iam_substrate.substrate_api.scoring.score_from_inputs")
    @patch("iam_substrate.substrate_api.database.get_session_local")
    def test_cursor_wraps_correctly_on_partial_last_page(self, mock_get_session, mock_score, mock_emit):
        """
        On a partial last page the cursor wraps back to 0 via modulo,
        ready to restart from the beginning on the next cycle.
        """
        import iam_substrate.substrate_api.role_decay as rd
        from iam_substrate.substrate_api.role_decay import emit_live_telemetry

        batch = rd._TELEMETRY_BATCH_LIMIT
        # 51 identities: first cycle gets 50, second cycle gets 1
        total = batch + 1
        first_batch = [_make_identity(f"id-{i:03d}", S=0.9) for i in range(batch)]
        partial_batch = [_make_identity("id-extra", S=0.9)]

        db1 = self._build_db_mock(first_batch, total=total)
        db2 = self._build_db_mock(partial_batch, total=total)
        mock_get_session.return_value.side_effect = [db1, db2]
        mock_score.return_value = self._mock_score_result()

        emit_live_telemetry()  # cycle 1: 50 identities, cursor = 50
        assert rd._telemetry_cursor == batch

        emit_live_telemetry()  # cycle 2: 1 identity, cursor = (50+1) % 51 = 0
        assert rd._telemetry_cursor == 0
