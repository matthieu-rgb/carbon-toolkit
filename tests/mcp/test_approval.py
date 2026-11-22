# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import threading
import time

from carbon.core.execute import Decision
from carbon.mcp.approval import (
    ApprovalQueue,
    DenyingApprover,
    PendingApproval,
    console_resolve,
)


def _start(q, tool="write_dtc", params=None):
    """Run q.request in a thread; return (thread, result dict) once registered."""
    result: dict = {}

    def run():
        result["d"] = q.request(tool, params or {"x": 1})

    t = threading.Thread(target=run)
    t.start()
    deadline = time.monotonic() + 5
    while not q.pending() and time.monotonic() < deadline:
        time.sleep(0)  # yield only; bounded poll, not a timing sync
    return t, result


def test_request_blocks_until_approved():
    q = ApprovalQueue(timeout=5)
    t, result = _start(q)
    pend = q.pending()
    assert len(pend) == 1 and isinstance(pend[0], PendingApproval)
    assert pend[0].tool == "write_dtc" and pend[0].params == {"x": 1}
    assert "d" not in result  # still blocked
    assert q.resolve(pend[0].id, Decision.APPROVED) is True
    t.join(5)
    assert not t.is_alive()
    assert result["d"] is Decision.APPROVED
    assert q.pending() == []


def test_request_denied():
    q = ApprovalQueue(timeout=5)
    t, result = _start(q)
    assert q.resolve(q.pending()[0].id, Decision.DENIED)
    t.join(5)
    assert result["d"] is Decision.DENIED


def test_request_times_out():
    q = ApprovalQueue(timeout=0.2)
    assert q.request("t", {}) is Decision.TIMEOUT
    assert q.pending() == []


def test_resolve_unknown_id_returns_false():
    assert ApprovalQueue().resolve("nope", Decision.APPROVED) is False


def test_double_resolve_second_returns_false():
    q = ApprovalQueue(timeout=5)
    t, result = _start(q)
    aid = q.pending()[0].id
    assert q.resolve(aid, Decision.APPROVED) is True
    assert q.resolve(aid, Decision.DENIED) is False
    t.join(5)
    assert result["d"] is Decision.APPROVED


def test_resolve_after_timeout_returns_false():
    q = ApprovalQueue(timeout=0.1)
    seen = []
    orig = q.request

    def run():
        seen.append(orig("t", {}))

    t = threading.Thread(target=run)
    t.start()
    while not q.pending() and t.is_alive():
        time.sleep(0)
    pend = q.pending()
    t.join(5)
    assert seen == [Decision.TIMEOUT]
    if pend:
        assert q.resolve(pend[0].id, Decision.APPROVED) is False


def test_denying_approver_denies():
    a = DenyingApprover()
    assert a.request("t", {}) is Decision.DENIED
    assert "aucun canal d'approbation" in a.reason


def test_console_resolve_approve():
    q = ApprovalQueue(timeout=5)
    t, result = _start(q)
    aid = q.pending()[0].id
    out: list[str] = []
    console_resolve(q, f"approve {aid}", out=out.append)
    t.join(5)
    assert result["d"] is Decision.APPROVED
    assert out


def test_console_resolve_deny():
    q = ApprovalQueue(timeout=5)
    t, result = _start(q)
    aid = q.pending()[0].id
    out: list[str] = []
    console_resolve(q, f"deny {aid}", out=out.append)
    t.join(5)
    assert result["d"] is Decision.DENIED


def test_console_resolve_list_and_bad_input():
    q = ApprovalQueue(timeout=5)
    out: list[str] = []
    console_resolve(q, "list", out=out.append)
    assert out
    t, result = _start(q, tool="flash_ecu")
    aid = q.pending()[0].id
    out.clear()
    console_resolve(q, "list", out=out.append)
    assert any(aid in l and "flash_ecu" in l for l in out)
    out.clear()
    console_resolve(q, "approve zzzz", out=out.append)
    console_resolve(q, "approve", out=out.append)
    console_resolve(q, "bogus", out=out.append)
    console_resolve(q, "", out=out.append)
    assert len(out) >= 3
    assert len(q.pending()) == 1
    q.resolve(aid, Decision.DENIED)
    t.join(5)
