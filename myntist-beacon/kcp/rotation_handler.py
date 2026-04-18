"""
Key Continuity Protocol — rotation handler.
"""
from __future__ import annotations

import time
from typing import Optional

from .key_state import (
    KeyState,
    create_genesis,
    get_latest_key_state,
    load_key_states,
    save_key_states,
)


def rotate_key(
    new_public_key: str,
    threshold_m: Optional[int] = None,
    threshold_n: Optional[int] = None,
) -> KeyState:
    """
    Rotate to a new key state.

    - Loads current state
    - Increments version
    - Sets parent_key_state_hash to the hash of the prior state
    - Appends new state and persists

    Args:
        new_public_key:  The new public key string
        threshold_m:     New M threshold (defaults to prior value)
        threshold_n:     New N threshold (defaults to prior value)

    Returns:
        The newly created KeyState
    """
    current = get_latest_key_state()

    if current is None:
        return create_genesis(new_public_key, threshold_m or 2, threshold_n or 3)

    parent_hash = current.compute_hash()
    new_state = KeyState(
        version=current.version + 1,
        public_key=new_public_key,
        threshold_m=threshold_m if threshold_m is not None else current.threshold_m,
        threshold_n=threshold_n if threshold_n is not None else current.threshold_n,
        parent_key_state_hash=parent_hash,
        created_at=time.time(),
        signature_chain=list(current.signature_chain) + [parent_hash],
    )

    states = load_key_states()
    states.append(new_state)
    save_key_states(states)
    return new_state


def initialize_if_needed(default_public_key: str = "genesis-key-placeholder") -> KeyState:
    """Ensure at least a genesis state exists."""
    existing = get_latest_key_state()
    if existing is not None:
        return existing
    return create_genesis(default_public_key)
