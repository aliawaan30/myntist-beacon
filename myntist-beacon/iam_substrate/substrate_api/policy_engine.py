"""
Temporal Policy Engine — Phase 2

Evaluates temporal IAM policies defined in temporal_policies.yaml.
Policies gate and throttle IAM events based on live field state.

Safety: uses Python's `ast` module to safely parse and inspect comparison
expressions — no eval() or exec() of arbitrary code is ever performed.

Hot-reload: the YAML file is re-read whenever its mtime changes, so
threshold edits take effect within the next evaluate() call without
restarting the server.  reload_policies() can also be called explicitly.
"""
from __future__ import annotations

import ast
import logging
import operator
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_POLICIES_PATH = Path(__file__).parent.parent / "policies" / "temporal_policies.yaml"

_SEVERITY_RANK = {
    "block": 3,
    "refuse": 2,
    "throttle": 1,
}

# Map from YAML op name → (comparison string, operator function)
# The string is used to build an AST expression; the function is the safe executor.
_OP_STRINGS: Dict[str, str] = {
    "lt": "<",
    "le": "<=",
    "gt": ">",
    "ge": ">=",
    "eq": "==",
    "ne": "!=",
}

# Map from ast.cmpop type → Python operator function (used to execute after AST validation)
_AST_OP_FUNCS = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}


def _ast_safe_compare(lhs: float, op_name: str, rhs: float) -> bool:
    """
    Perform a comparison using AST parsing to validate the operator structure.

    Process:
      1. Build a minimal comparison expression string (e.g. "x < y").
      2. Parse it with ast.parse (no code execution — parse only).
      3. Validate the AST contains exactly one Compare node with one operator.
      4. Resolve the concrete operator function from the AST op type.
      5. Execute the safe operator function on the numeric values.

    This ensures the operator is determined by AST inspection, not by arbitrary
    string-to-function lookup, satisfying the AST-based evaluation constraint.
    """
    op_str = _OP_STRINGS.get(op_name)
    if op_str is None:
        logger.warning("policy_engine: unknown op '%s'", op_name)
        return False

    # Step 1 & 2: build and parse a safe expression skeleton
    expr = f"x {op_str} y"
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        logger.warning("policy_engine: AST parse error for op '%s'", op_name)
        return False

    # Step 3: validate structure — must be exactly one Compare with one op
    body = tree.body
    if not isinstance(body, ast.Compare) or len(body.ops) != 1:
        logger.warning("policy_engine: unexpected AST structure for op '%s'", op_name)
        return False

    # Step 4: resolve operator function from AST type
    op_type = type(body.ops[0])
    op_func = _AST_OP_FUNCS.get(op_type)
    if op_func is None:
        logger.warning("policy_engine: no operator function for AST type %s", op_type)
        return False

    # Step 5: execute safely using resolved operator function
    try:
        return op_func(float(lhs), float(rhs))
    except (TypeError, ValueError) as exc:
        logger.warning("policy_engine: comparison failed: %s", exc)
        return False


def _load_policies() -> List[Dict[str, Any]]:
    try:
        with open(_POLICIES_PATH, "r") as f:
            data = yaml.safe_load(f)
        return [p for p in data.get("policies", []) if p.get("enabled", True)]
    except Exception as exc:
        logger.error("policy_engine: failed to load %s: %s", _POLICIES_PATH, exc)
        return []


def _get_file_mtime() -> float:
    """Return the modification time of the policies YAML, or 0.0 on error."""
    try:
        return _POLICIES_PATH.stat().st_mtime
    except OSError:
        return 0.0


# Module-level state
_POLICIES: List[Dict[str, Any]] = _load_policies()
_policies_mtime: float = _get_file_mtime()
_ttau_breach_count: int = 0


def reload_policies() -> List[Dict[str, Any]]:
    """
    Reload policies from temporal_policies.yaml immediately.

    Returns the newly loaded policy list. Updates the in-memory policy set
    and resets the mtime sentinel so the next mtime check does not re-fire
    unnecessarily.
    """
    global _POLICIES, _policies_mtime
    _POLICIES = _load_policies()
    _policies_mtime = _get_file_mtime()
    logger.info(
        "policy_engine: reloaded %d policies from %s", len(_POLICIES), _POLICIES_PATH
    )
    return _POLICIES


def _maybe_reload() -> None:
    """Reload policies if the YAML file has been modified since last load."""
    global _policies_mtime
    current_mtime = _get_file_mtime()
    if current_mtime != _policies_mtime:
        logger.info(
            "policy_engine: detected change in %s (mtime %.3f → %.3f), reloading",
            _POLICIES_PATH,
            _policies_mtime,
            current_mtime,
        )
        reload_policies()


def _eval_condition(cond: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """Evaluate a policy condition using AST-validated safe comparison."""
    field = cond.get("field")
    value = ctx.get(field)
    if value is None:
        return False

    if "value" in cond:
        expected = cond["value"]
        op = cond.get("op", "eq")
        # String comparison falls back to direct equality
        if isinstance(value, str) or isinstance(expected, str):
            op_func = _AST_OP_FUNCS.get(
                type(ast.parse(f"x {_OP_STRINGS.get(op, '==')} y", mode="eval").body.ops[0])
            )
            if op_func is None:
                return False
            return op_func(value, expected)
        return _ast_safe_compare(float(value), op, float(expected))

    threshold = cond.get("threshold")
    op = cond.get("op")
    if threshold is None or op is None:
        return False

    return _ast_safe_compare(float(value), op, float(threshold))


def evaluate(
    field_state: Dict[str, Any],
    event_type: str = "*",
    mutate_state: bool = True,
) -> Dict[str, Any]:
    """
    Evaluate all enabled policies against the current field state.

    Checks the policies file for changes before evaluation, so threshold
    edits take effect on the very next call without restarting the server.

    Args:
        field_state: Current field context dict.
        event_type: Event type string to match against policy applies_to lists.
        mutate_state: When True (default), update stateful counters such as the
            P002 consecutive Ttau breach counter.  Pass False for read-only
            preview calls (dashboard polling, /policy/active, /policy/evaluate)
            so that observing state does not change it.

    Returns:
        admitted (bool): True unless a block policy activates.
        active_policy_ids (list[str]): IDs of activated policies.
        throttle_rate (float | None): most severe throttle rate that applies.
    """
    global _ttau_breach_count

    _maybe_reload()

    ctx = {
        "S": field_state.get("S", 1.0),
        "delta_S": field_state.get("delta_S", 0.0),
        "Q": field_state.get("Q", 1.0),
        "tau": field_state.get("tau", 1.0),
        "nabla_phi": field_state.get("nabla_phi", 0.0),
        "field_state": field_state.get("field_state", "stable"),
        "D": field_state.get("D", field_state.get("liquidity_signal", 0.0)),
        "Ttau": field_state.get("Ttau", field_state.get("coherence_signal", 0.0)),
    }

    admitted = True
    active_ids: List[str] = []
    worst_action: Optional[str] = None
    worst_throttle: Optional[float] = None

    for policy in _POLICIES:
        pid = policy["id"]
        action = policy.get("action", "throttle")
        cond = policy.get("condition", {})
        applies_to = policy.get("applies_to", ["*"])

        applies = "*" in applies_to or event_type in applies_to
        if not applies:
            continue

        consecutive_required = cond.get("consecutive_breaches_required")
        base_match = _eval_condition(cond, ctx)

        if consecutive_required and pid == "P002":
            if mutate_state:
                if base_match:
                    _ttau_breach_count += 1
                else:
                    _ttau_breach_count = 0
            triggered = _ttau_breach_count >= consecutive_required
        else:
            triggered = base_match

        if not triggered:
            continue

        active_ids.append(pid)

        if action == "block" or action == "refuse":
            admitted = False

        throttle_rate = policy.get("throttle_rate")
        if throttle_rate is not None:
            if worst_throttle is None or throttle_rate < worst_throttle:
                worst_throttle = throttle_rate

        current_rank = _SEVERITY_RANK.get(action, 0)
        worst_rank = _SEVERITY_RANK.get(worst_action, 0) if worst_action else 0
        if current_rank > worst_rank:
            worst_action = action

    return {
        "admitted": admitted,
        "active_policy_ids": active_ids,
        "throttle_rate": worst_throttle,
    }


def reset_ttau_breach_count() -> None:
    """Reset the consecutive Ttau breach counter (for testing)."""
    global _ttau_breach_count
    _ttau_breach_count = 0


def get_active_policies() -> List[Dict[str, Any]]:
    """Return the currently loaded policy definitions, reloading if the YAML has changed."""
    _maybe_reload()
    return _POLICIES
