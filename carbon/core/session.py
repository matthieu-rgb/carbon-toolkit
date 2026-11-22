# SPDX-License-Identifier: GPL-3.0-or-later
"""In-process session: shared registry, journal, bus config and result history."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from carbon.core.execute import Approver, Origin, execute_tool
from carbon.core.journal import Journal
from carbon.core.result import ToolResult


class Session:
    def __init__(
        self,
        *,
        channel: str,
        interface: str = "socketcan",
        journal_path: Path,
        approver: Approver | None = None,
        history_limit: int = 50,
    ) -> None:
        from carbon.cli import build_registry  # local import: avoid import cycles

        self.registry = build_registry()
        self.journal = Journal(journal_path)
        self.channel = channel
        self.interface = interface
        self.approver = approver
        self.history_limit = history_limit
        self.history: list[ToolResult] = []

    def run_tool(
        self,
        name: str,
        *,
        origin: Origin = Origin.MCP,
        assume_yes: bool = False,
        interactive: bool = False,
        **tool_params: Any,
    ) -> ToolResult:
        adapter = self.registry.get(name)
        params = {**tool_params, "channel": self.channel, "interface": self.interface}
        result = execute_tool(
            adapter,
            params,
            origin=origin,
            journal=self.journal,
            assume_yes=assume_yes,
            interactive=interactive,
            approver=self.approver,
        )
        self.history.append(result)
        if self.history_limit > 0:
            del self.history[: -self.history_limit]
        return result

    def state(self) -> dict[str, Any]:
        return {
            "tools": self.registry.names(),
            "methodology": {"mode": "libre", "loaded": False},
            "history": [r.to_dict() for r in self.history],
            "channel": self.channel,
            "interface": self.interface,
        }

    def journal_text(self) -> str:
        path = self.journal.path
        return path.read_text(encoding="utf-8") if path.exists() else ""
