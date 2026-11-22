# SPDX-License-Identifier: GPL-3.0-or-later
"""In-process session: shared registry, journal, bus config and result history."""
from __future__ import annotations

import contextlib
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from carbon.core.execute import Approver, Origin, execute_tool
from carbon.core.journal import Journal
from carbon.core.registry_builder import build_registry
from carbon.core.result import ToolResult
from carbon.methodology.engine import Engine
from carbon.methodology.loader import load_methodology
from carbon.methodology.persistence import load_state, save_state


class Session:
    def __init__(
        self,
        *,
        channel: str,
        interface: str = "socketcan",
        journal_path: Path,
        approver: Approver | None = None,
        history_limit: int = 50,
        engine: Engine | None = None,
        state_path: Path | None = None,
        methodology_ref: str | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.registry = build_registry()
        self.journal = Journal(journal_path)
        self.channel = channel
        self.interface = interface
        self.approver = approver
        self.history_limit = history_limit
        self.history: list[ToolResult] = []
        self.engine = engine
        self.state_path = Path(state_path) if state_path is not None else None
        self.methodology_ref = methodology_ref
        self._lock = threading.Lock()
        self.on_change = on_change

    @property
    def mode(self) -> str:
        return self.engine.mode if self.engine is not None else "libre"

    def _persist(self) -> None:
        if self.engine is not None and self.state_path is not None:
            save_state(self.state_path, methodology_ref=self.methodology_ref or "",
                       engine=self.engine)

    def _require_engine(self) -> Engine:
        if self.engine is None:
            raise RuntimeError("aucune méthodologie chargée")
        return self.engine

    def load_methodology(self, source: str | Path) -> None:
        meth = load_methodology(source, known_tools=set(self.registry.names()))
        self.engine = Engine(meth)
        self.methodology_ref = str(Path(source).resolve())
        self._persist()

    def set_mode(self, mode: str) -> None:
        self._require_engine().set_mode(mode)
        self._persist()

    def step_ack(self) -> None:
        self._require_engine().ack()
        self._persist()

    def step_choose(self, step_id: str) -> None:
        self._require_engine().choose(step_id)
        self._persist()

    @classmethod
    def resume(
        cls,
        state_path: Path,
        *,
        channel: str,
        interface: str = "socketcan",
        journal_path: Path,
        approver: Approver | None = None,
        history_limit: int = 50,
    ) -> "Session":
        """Rebuild a Session whose engine position is restored from state_path.

        Restores POSITION only (step, mode, history, pending choice); the
        target is never contacted. Raises StateError on a bad state file.
        """
        s = cls(channel=channel, interface=interface, journal_path=journal_path,
                approver=approver, history_limit=history_limit,
                state_path=state_path)
        known = set(s.registry.names())
        ref, engine = load_state(
            state_path,
            resolve_methodology=lambda r: load_methodology(r, known_tools=known))
        s.engine, s.methodology_ref = engine, ref
        return s

    def run_tool(
        self,
        name: str,
        *,
        origin: Origin = Origin.MCP,
        assume_yes: bool = False,
        interactive: bool = False,
        **tool_params: Any,
    ) -> ToolResult:
        if (self.engine is not None and self.engine.mode == "guided"
                and not self.engine.allowed(name)):
            now = datetime.now(timezone.utc)
            return ToolResult(
                tool=name, ok=False, started_at=now, ended_at=now,
                summary=f"hors parcours guidé: {name} n'est pas l'étape courante")
        adapter = self.registry.get(name)
        params = {**tool_params, "channel": self.channel, "interface": self.interface}
        # Destructive tools may block for a long time waiting on the Approver;
        # holding the lock there would freeze every other tool call, so only
        # the post-execution state update is serialized for them.
        destructive = bool(getattr(adapter, "destructive", False))
        with contextlib.ExitStack() as stack:
            if not destructive:
                stack.enter_context(self._lock)
            result = execute_tool(
                adapter,
                params,
                origin=origin,
                journal=self.journal,
                assume_yes=assume_yes,
                interactive=interactive,
                approver=self.approver,
            )
            if destructive:
                stack.enter_context(self._lock)
            if self.engine is not None:
                self.engine.observe(name, result.to_dict())
                self._persist()
            self.history.append(result)
            if self.history_limit > 0:
                del self.history[: -self.history_limit]
        if self.on_change is not None:
            self.on_change()
        return result

    def _methodology_state(self) -> dict[str, Any]:
        e = self.engine
        if e is None:
            return {"mode": "libre", "loaded": False}
        cur = e.current()
        return {
            "loaded": True,
            "mode": e.mode,
            "current": {"id": cur.id, "title": cur.title,
                        "objective": cur.objective, "tool": cur.tool},
            "candidates": [{"id": c.id, "title": c.title, "tool": c.tool}
                           for c in e.candidates()],
            "pending_choice": e.pending_choice,
            "satisfied": e.satisfied,
        }

    def state(self) -> dict[str, Any]:
        return {
            "tools": self.registry.names(),
            "methodology": self._methodology_state(),
            "history": [r.to_dict() for r in self.history],
            "channel": self.channel,
            "interface": self.interface,
        }

    def journal_text(self) -> str:
        path = self.journal.path
        return path.read_text(encoding="utf-8") if path.exists() else ""
