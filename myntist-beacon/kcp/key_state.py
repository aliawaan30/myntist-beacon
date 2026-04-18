"""
Key Continuity Protocol — KeyState dataclass and persistence.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

KCP_DIR = Path(__file__).parent
KEY_STATES_FILE = KCP_DIR / "key_states.json"


@dataclass
class KeyState:
    version: int
    public_key: str
    threshold_m: int
    threshold_n: int
    parent_key_state_hash: str
    created_at: float
    signature_chain: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "KeyState":
        return cls(
            version=d["version"],
            public_key=d["public_key"],
            threshold_m=d["threshold_m"],
            threshold_n=d["threshold_n"],
            parent_key_state_hash=d["parent_key_state_hash"],
            created_at=d["created_at"],
            signature_chain=d.get("signature_chain", []),
        )

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 hash of this key state."""
        payload = (
            f"{self.version}"
            f"{self.public_key}"
            f"{self.threshold_m}"
            f"{self.threshold_n}"
            f"{self.parent_key_state_hash}"
            f"{self.created_at}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def load_key_states() -> List[KeyState]:
    """Load all key states from the JSON file."""
    if not KEY_STATES_FILE.exists():
        return []
    with open(KEY_STATES_FILE, "r") as f:
        data = json.load(f)
    return [KeyState.from_dict(d) for d in data]


def save_key_states(states: List[KeyState]) -> None:
    """Persist key states to JSON file."""
    with open(KEY_STATES_FILE, "w") as f:
        json.dump([s.to_dict() for s in states], f, indent=2)


def create_genesis(public_key: str, threshold_m: int = 2, threshold_n: int = 3) -> KeyState:
    """Create the genesis key state (version=0, parent_hash='genesis')."""
    genesis = KeyState(
        version=0,
        public_key=public_key,
        threshold_m=threshold_m,
        threshold_n=threshold_n,
        parent_key_state_hash="genesis",
        created_at=time.time(),
        signature_chain=[],
    )
    save_key_states([genesis])
    return genesis


def get_latest_key_state() -> Optional[KeyState]:
    """Return the highest-version key state, or None if no states exist."""
    states = load_key_states()
    if not states:
        return None
    return max(states, key=lambda s: s.version)
