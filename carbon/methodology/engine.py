# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic methodology engine: pure logic, no tool execution, no bus.

Rules:
- observe(): only a result from the current step's tool can advance.
  Exactly one matching edge advances; 0 or >1 matches leave the pointer and
  set ``pending_choice`` (matching targets for >1; ALL candidates for 0, so the
  user always has a menu to pick from).
- ack(): for a step with no tool, postconditions are vacuously satisfied and
  branches are evaluated against an empty result ({}), so only ``when=None``
  edges match (a ``when`` needing data is not matched). On a step with a tool,
  ack() is a no-op.
"""
from __future__ import annotations

from carbon.methodology.conditions import evaluate
from carbon.methodology.schema import Methodology, Step

MODES = ("guided", "libre")


def _check_mode(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"invalid mode {mode!r}; expected one of {MODES}")


class Engine:
    def __init__(self, methodology: Methodology, *, mode: str = "guided") -> None:
        _check_mode(mode)
        self.methodology = methodology
        self.current_id: str = methodology.start
        self.mode = mode
        self.history: list[dict] = []
        self.pending_choice: list[str] | None = None
        self.satisfied: bool | None = None

    def current(self) -> Step:
        return self.methodology.steps[self.current_id]

    def candidates(self) -> list[Step]:
        return [self.methodology.steps[e.to] for e in self.current().next]

    def _branch(self, result: dict) -> None:
        edges = self.current().next
        if not edges:
            self.pending_choice = None
            return
        matched = [e.to for e in edges
                   if e.when is None or evaluate(e.when, result)]
        if len(matched) == 1:
            self.current_id = matched[0]
            self.pending_choice = None
        elif matched:
            self.pending_choice = matched
        else:
            self.pending_choice = [e.to for e in edges]

    def observe(self, tool: str, result: dict) -> None:
        step = self.current()
        entry = {"step": step.id, "tool": tool, "ok": bool(result.get("ok")),
                 "off_step": tool != step.tool}
        self.history.append(entry)
        if tool != step.tool:
            return
        self.satisfied = all(evaluate(c, result) for c in step.conditions)
        entry["satisfied"] = self.satisfied
        self._branch(result)

    def choose(self, step_id: str) -> None:
        if step_id not in {c.id for c in self.candidates()}:
            raise ValueError(f"{step_id!r} is not a candidate of {self.current_id!r}")
        self.current_id = step_id
        self.pending_choice = None
        self.satisfied = None

    def ack(self) -> None:
        if self.current().tool is not None:
            return
        self.satisfied = True
        self.history.append({"step": self.current_id, "tool": None,
                             "ok": True, "off_step": False, "ack": True})
        self._branch({})

    def allowed(self, tool: str) -> bool:
        if self.mode == "libre":
            return True
        tools = {self.current().tool} | {c.tool for c in self.candidates()}
        tools.discard(None)
        return tool in tools

    def set_mode(self, mode: str) -> None:
        _check_mode(mode)
        self.mode = mode

    def position(self) -> dict:
        return {"current_id": self.current_id, "mode": self.mode,
                "pending_choice": self.pending_choice,
                "satisfied": self.satisfied}

    def to_dict(self) -> dict:
        return {"current_id": self.current_id, "mode": self.mode,
                "history": [dict(h) for h in self.history],
                "pending_choice": (list(self.pending_choice)
                                   if self.pending_choice is not None else None),
                "satisfied": self.satisfied}

    @classmethod
    def from_dict(cls, d: dict, methodology: Methodology) -> "Engine":
        e = cls(methodology, mode=d.get("mode", "guided"))
        e.current_id = d["current_id"]
        e.history = [dict(h) for h in d.get("history", [])]
        pc = d.get("pending_choice")
        e.pending_choice = list(pc) if pc is not None else None
        e.satisfied = d.get("satisfied")
        return e
