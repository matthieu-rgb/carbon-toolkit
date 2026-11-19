# SPDX-License-Identifier: GPL-3.0-or-later
"""Append-only JSONL audit journal."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from carbon.core.result import ToolResult


class JournalError(Exception):
    """Raised when a journal entry cannot be written."""


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(self, result: ToolResult, params: dict[str, Any], actor: str) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "tool": result.tool,
            "params": params,
            "ok": result.ok,
            "summary": result.summary,
        }
        try:
            line = json.dumps(entry, ensure_ascii=False) + "\n"
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        except (OSError, TypeError, ValueError) as exc:
            raise JournalError(f"cannot write journal {self.path}: {exc}") from exc
