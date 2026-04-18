"""
Tests for kcp/ — key continuity protocol.
"""
import os
import sys
import json
import time
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


class TestKeyState:
    def setup_method(self):
        """Use a temp directory for key_states.json."""
        self.tmpdir = tempfile.mkdtemp()
        import kcp.key_state as ks_mod
        self._orig_file = ks_mod.KEY_STATES_FILE
        ks_mod.KEY_STATES_FILE = Path(self.tmpdir) / "key_states.json"

    def teardown_method(self):
        import kcp.key_state as ks_mod
        ks_mod.KEY_STATES_FILE = self._orig_file
        shutil.rmtree(self.tmpdir)

    def test_genesis_created_correctly(self):
        from kcp.key_state import create_genesis, load_key_states
        genesis = create_genesis("test-pub-key-genesis")
        assert genesis.version == 0
        assert genesis.public_key == "test-pub-key-genesis"
        assert genesis.parent_key_state_hash == "genesis"
        states = load_key_states()
        assert len(states) == 1
        assert states[0].version == 0

    def test_version_increments_on_rotation(self):
        from kcp.key_state import create_genesis
        from kcp.rotation_handler import rotate_key
        create_genesis("key-v0")
        state_v1 = rotate_key("key-v1")
        state_v2 = rotate_key("key-v2")
        assert state_v1.version == 1
        assert state_v2.version == 2

    def test_parent_hash_set_on_rotation(self):
        from kcp.key_state import create_genesis
        from kcp.rotation_handler import rotate_key
        genesis = create_genesis("key-v0")
        state_v1 = rotate_key("key-v1")
        assert state_v1.parent_key_state_hash == genesis.compute_hash()


class TestContinuityVerifier:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        import kcp.key_state as ks_mod
        self._orig_file = ks_mod.KEY_STATES_FILE
        ks_mod.KEY_STATES_FILE = Path(self.tmpdir) / "key_states.json"

    def teardown_method(self):
        import kcp.key_state as ks_mod
        ks_mod.KEY_STATES_FILE = self._orig_file
        shutil.rmtree(self.tmpdir)

    def test_all_7_invariants_pass_on_valid_chain(self):
        from kcp.key_state import create_genesis
        from kcp.rotation_handler import rotate_key
        from kcp.continuity_verifier import verify_continuity

        create_genesis("key-v0")
        rotate_key("key-v1")
        rotate_key("key-v2")

        result = verify_continuity()
        assert result["all_pass"] is True
        for i in range(1, 8):
            assert result["results"][f"invariant_{i}"] == "pass", \
                f"Invariant {i} failed: {result}"

    def test_continuity_verifier_fails_on_tampered_chain(self):
        from kcp.key_state import create_genesis, load_key_states, save_key_states
        from kcp.rotation_handler import rotate_key
        from kcp.continuity_verifier import verify_continuity

        create_genesis("key-v0")
        rotate_key("key-v1")

        states = load_key_states()
        tampered = states.copy()
        # Tamper: change parent_hash of v1 to break chain
        tampered[1].parent_key_state_hash = "tampered_hash"
        save_key_states(tampered)

        result = verify_continuity()
        assert result["all_pass"] is False
        assert result["results"]["invariant_3"] == "fail"

    def test_genesis_only_passes_invariants(self):
        from kcp.key_state import create_genesis
        from kcp.continuity_verifier import verify_continuity

        create_genesis("key-v0")
        result = verify_continuity()
        assert result["all_pass"] is True

    def test_missing_genesis_fails_invariant_1(self):
        from kcp.key_state import KeyState, save_key_states
        from kcp.continuity_verifier import verify_continuity
        import time

        # Insert a state with wrong parent hash (no genesis)
        fake_state = KeyState(
            version=0,
            public_key="k",
            threshold_m=2,
            threshold_n=3,
            parent_key_state_hash="not-genesis",
            created_at=time.time(),
        )
        save_key_states([fake_state])
        result = verify_continuity()
        assert result["results"]["invariant_1"] == "fail"
