# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared guard -> run -> journal pipeline used by both the CLI and the MCP server."""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Protocol

from carbon.can.bus import BusError
from carbon.core.adapter import Adapter
from carbon.core.confirm import authorize
from carbon.core.journal import Journal
from carbon.core.result import ToolResult
from carbon.uds.connection import UdsError


class Origin(enum.Enum):
    CLI = "cli"
    MCP = "mcp"
    TUI = "tui"


class Decision(enum.Enum):
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"


class ActionRefused(Exception):
    """CLI-origin destructive action refused (not journaled)."""


class Approver(Protocol):
    def request(self, tool: str, params: dict) -> Decision: ...


def _jsonable(params: dict) -> dict:
    return {k: (v.hex() if isinstance(v, bytes) else v) for k, v in params.items()}


def _failure(tool: str, summary: str) -> ToolResult:
    now = datetime.now(timezone.utc)
    return ToolResult(tool=tool, ok=False, summary=summary, started_at=now, ended_at=now,
                      data={}, artifacts=[])


def execute_tool(
    adapter: Adapter,
    params: dict,
    *,
    origin: Origin,
    journal: Journal,
    assume_yes: bool = False,
    interactive: bool = False,
    approver: Approver | None = None,
    prompt_fn=input,
) -> ToolResult:
    safe_params = _jsonable(params)
    result: ToolResult | None = None

    if adapter.destructive:
        if origin is Origin.CLI:
            if not authorize(adapter, assume_yes=assume_yes, interactive=interactive,
                             prompt_fn=prompt_fn):
                raise ActionRefused(adapter.name)
        else:
            # assume_yes is deliberately ignored: every non-CLI origin (MCP, TUI) needs explicit human approval.
            decision = (Decision.DENIED if approver is None
                        else approver.request(adapter.name, safe_params))
            if decision is not Decision.APPROVED:
                reason = getattr(approver, "reason", None)
                summary = f"{adapter.name}: {decision.value} (human approval)"
                if reason:
                    summary += f" - {reason}"
                result = _failure(adapter.name, summary)

    if result is None:
        try:
            result = adapter.run(**params)
        except (BusError, UdsError, ValueError, OSError) as exc:
            result = _failure(adapter.name, f"failed: {exc}")

    journal.record(result, safe_params, origin.value)
    return result
