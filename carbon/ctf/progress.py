# SPDX-License-Identifier: GPL-3.0-or-later
"""Local, per-user CTF progress: a small JSON file, no server.

Keeps challenge solve state and hints revealed, so definitions stay immutable and
progress survives across sessions offline.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_progress_path() -> Path:
    """``$CARBON_HOME`` or ``~/.carbon`` -> ``ctf_progress.json``."""
    base = os.environ.get("CARBON_HOME")
    root = Path(base) if base else Path.home() / ".carbon"
    return root / "ctf_progress.json"


class Progress:
    """Solve/hint state, keyed by challenge id."""

    def __init__(self, path: Path, data: dict[str, Any] | None = None) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = data or {}

    # ---- queries ----
    def is_solved(self, cid: str) -> bool:
        return bool(self.data.get(cid, {}).get("solved"))

    def hints_used(self, cid: str) -> int:
        return int(self.data.get(cid, {}).get("hints_used", 0))

    def solved_ids(self) -> set[str]:
        return {cid for cid, v in self.data.items() if v.get("solved")}

    # ---- mutations ----
    def _entry(self, cid: str) -> dict[str, Any]:
        return self.data.setdefault(cid, {})

    def mark_solved(self, cid: str) -> None:
        e = self._entry(cid)
        if not e.get("solved"):
            e["solved"] = True
            e["solved_at"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def record_attempt(self, cid: str) -> None:
        e = self._entry(cid)
        e["attempts"] = int(e.get("attempts", 0)) + 1
        self.save()

    def reveal_hint(self, cid: str) -> None:
        e = self._entry(cid)
        e["hints_used"] = int(e.get("hints_used", 0)) + 1
        self.save()

    def reset(self, cid: str) -> None:
        self.data.pop(cid, None)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # atomic replace, so a crash never truncates progress
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ctf-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def load_progress(path: Path) -> Progress:
    """Load progress, tolerating a missing or unreadable file (fresh start)."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    return Progress(p, data)
