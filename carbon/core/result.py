# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured result contract returned by every CARBON tool."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    tool: str
    ok: bool
    summary: str
    started_at: datetime
    ended_at: datetime
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "summary": self.summary,
            "data": self.data,
            "artifacts": list(self.artifacts),
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ToolResult:
        return cls(
            tool=d["tool"],
            ok=d["ok"],
            summary=d["summary"],
            data=d.get("data", {}),
            artifacts=list(d.get("artifacts", [])),
            started_at=datetime.fromisoformat(d["started_at"]),
            ended_at=datetime.fromisoformat(d["ended_at"]),
        )
