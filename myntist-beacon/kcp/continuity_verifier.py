"""
Key Continuity Protocol — verifies all 7 continuity invariants.
"""
from __future__ import annotations

from typing import Dict, Any

from .key_state import load_key_states, KeyState


def verify_continuity() -> Dict[str, Any]:
    """
    Verify all 7 KCP continuity invariants.

    Invariants:
        1. Keys define authority not identity (genesis exists)
        2. Continuity is append-only (no gaps in version sequence)
        3. Key changes are chained (each parent_hash matches prior state hash)
        4. No silent replacement (version strictly increasing)
        5. No retroactive insertion (timestamps monotonic)
        6. No downgrade (version never decreases)
        7. Observer can verify (all hashes recomputable)

    Returns:
        {
            all_pass: bool,
            results: {
                invariant_1: "pass" | "fail",
                ...
                invariant_7: "pass" | "fail",
            }
        }
    """
    states = load_key_states()
    results: Dict[str, str] = {}

    # Sort by version for sequential analysis
    sorted_states = sorted(states, key=lambda s: s.version)

    # Invariant 1: Genesis exists (version=0, parent_hash="genesis")
    has_genesis = any(
        s.version == 0 and s.parent_key_state_hash == "genesis"
        for s in sorted_states
    )
    results["invariant_1"] = "pass" if has_genesis else "fail"

    # Invariant 2: No gaps in version sequence
    versions = [s.version for s in sorted_states]
    expected = list(range(len(sorted_states)))
    results["invariant_2"] = "pass" if versions == expected else "fail"

    # Invariant 3: Each parent_hash matches the hash of the prior state
    inv3_pass = True
    for i in range(1, len(sorted_states)):
        prior = sorted_states[i - 1]
        current = sorted_states[i]
        if current.parent_key_state_hash != prior.compute_hash():
            inv3_pass = False
            break
    results["invariant_3"] = "pass" if inv3_pass else "fail"

    # Invariant 4: Version strictly increasing (no silent replacement)
    inv4_pass = all(
        sorted_states[i].version > sorted_states[i - 1].version
        for i in range(1, len(sorted_states))
    )
    results["invariant_4"] = "pass" if (len(sorted_states) <= 1 or inv4_pass) else "fail"

    # Invariant 5: Timestamps monotonic (no retroactive insertion)
    inv5_pass = all(
        sorted_states[i].created_at >= sorted_states[i - 1].created_at
        for i in range(1, len(sorted_states))
    )
    results["invariant_5"] = "pass" if (len(sorted_states) <= 1 or inv5_pass) else "fail"

    # Invariant 6: No downgrade (version never decreases — same as strictly increasing when sorted)
    raw_versions = [s.version for s in states]
    inv6_pass = raw_versions == sorted(raw_versions)
    results["invariant_6"] = "pass" if inv6_pass else "fail"

    # Invariant 7: All hashes are recomputable (observer can verify)
    inv7_pass = True
    for i in range(1, len(sorted_states)):
        recomputed = sorted_states[i - 1].compute_hash()
        if sorted_states[i].parent_key_state_hash != recomputed:
            inv7_pass = False
            break
    results["invariant_7"] = "pass" if inv7_pass else "fail"

    all_pass = all(v == "pass" for v in results.values())
    return {"all_pass": all_pass, "results": results}
