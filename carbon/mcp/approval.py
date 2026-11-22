# SPDX-License-Identifier: GPL-3.0-or-later
"""Blocking human-approval queue for destructive MCP actions.

The requesting thread blocks on a ``threading.Event`` until an operator,
through a channel the AI cannot reach (console), posts a decision.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Callable

from carbon.core.execute import Decision


@dataclass
class PendingApproval:
    id: str
    tool: str
    params: dict
    # Internal synchronisation state; not part of the public constructor/repr.
    _event: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False, compare=False
    )
    _decision: Decision | None = field(default=None, init=False, repr=False, compare=False)


class ApprovalQueue:
    """Implements ``carbon.core.execute.Approver``."""

    def __init__(self, timeout: float = 300.0) -> None:
        self._timeout = timeout
        self._lock = threading.Lock()
        self._table: dict[str, PendingApproval] = {}

    def request(self, tool: str, params: dict) -> Decision:
        try:
            with self._lock:
                aid = secrets.token_hex(2)
                while aid in self._table:
                    aid = secrets.token_hex(2)
                entry = PendingApproval(id=aid, tool=tool, params=params)
                self._table[aid] = entry
            entry._event.wait(self._timeout)
            with self._lock:
                self._table.pop(aid, None)
                # A decision posted right at expiry still wins (it was accepted).
                return entry._decision if entry._decision is not None else Decision.TIMEOUT
        except Exception:  # never raise: caller must always be able to journal
            return Decision.DENIED

    def pending(self) -> list[PendingApproval]:
        with self._lock:
            return list(self._table.values())

    def resolve(self, approval_id: str, decision: Decision) -> bool:
        with self._lock:
            entry = self._table.get(approval_id)
            if entry is None or entry._decision is not None:
                return False
            entry._decision = decision
            entry._event.set()
            return True


class DenyingApprover:
    """Approver for stdio mode: there is no human channel, so always deny."""

    reason = "aucun canal d'approbation (mode stdio) : action destructive refusée"

    def request(self, tool: str, params: dict) -> Decision:
        return Decision.DENIED


def console_resolve(queue: ApprovalQueue, line: str, *, out: Callable[[str], object] = print) -> None:
    """Handle one operator line: ``list``, ``approve <id>``, ``deny <id>``."""
    parts = line.split()
    if not parts:
        return out("commande vide (list | approve <id> | deny <id>)")
    cmd = parts[0].lower()
    if cmd == "list":
        pend = queue.pending()
        if not pend:
            return out("aucune approbation en attente")
        for p in pend:
            out(f"{p.id}  {p.tool}  {p.params}")
        return None
    if cmd in ("approve", "deny"):
        if len(parts) != 2:
            return out(f"usage : {cmd} <id>")
        decision = Decision.APPROVED if cmd == "approve" else Decision.DENIED
        if queue.resolve(parts[1], decision):
            return out(f"{parts[1]} : {decision.value}")
        return out(f"{parts[1]} : id inconnu ou déjà résolu")
    return out(f"commande inconnue : {cmd} (list | approve <id> | deny <id>)")
