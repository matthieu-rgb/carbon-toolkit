# SPDX-License-Identifier: GPL-3.0-or-later
"""Closed condition grammar evaluated over a ToolResult.to_dict().

No eval, no deep paths: a path is "ok" or "data.<key>" (one level).
A missing path yields False; a malformed condition raises ValueError.
"""
from __future__ import annotations

from typing import Any


def _resolve(path: str, result: dict) -> tuple[bool, object]:
    """Return (found, value) for "ok" or "data.<key>"."""
    if path == "ok":
        return ("ok" in result, result.get("ok"))
    if isinstance(path, str) and path.startswith("data."):
        key = path[len("data."):]
        data = result.get("data")
        if key and "." not in key and isinstance(data, dict) and key in data:
            return True, data[key]
    return False, None


def evaluate(cond: dict, result: dict) -> bool:
    if not isinstance(cond, dict) or len(cond) != 1:
        raise ValueError(f"malformed condition: {cond!r}")
    (op, arg), = cond.items()
    if op == "ok":
        return result.get("ok") == arg
    if op in ("all", "any"):
        if not isinstance(arg, list):
            raise ValueError(f"'{op}' expects a list: {cond!r}")
        fn = all if op == "all" else any
        return fn(evaluate(c, result) for c in arg)
    if op in ("exists", "truthy"):
        found, val = _resolve(arg, result)
        return found if op == "exists" else (found and bool(val))
    if op in ("equals", "contains"):
        if not isinstance(arg, list) or len(arg) != 2:
            raise ValueError(f"'{op}' expects [path, value]: {cond!r}")
        found, val = _resolve(arg[0], result)
        if not found:
            return False
        if op == "equals":
            return val == arg[1]
        try:
            return arg[1] in val  # type: ignore[operator]
        except TypeError:
            return False
    raise ValueError(f"unknown condition key: {op!r}")
