# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import threading

from carbon.core.execute import Decision
from carbon.mcp.approval import ApprovalQueue


def _run(q, out, done):
    def w():
        out.append(q.request("flash", {"a": 1}))
        done.set()
    t = threading.Thread(target=w, daemon=True)
    t.start()
    return t


def test_callback_called_once_and_resolve_from_main_thread():
    seen, fired = [], threading.Event()

    def cb(entry):
        seen.append((entry.id, entry.tool, entry.params))
        fired.set()

    q = ApprovalQueue(timeout=5, on_pending=cb)
    out, done = [], threading.Event()
    _run(q, out, done)
    assert fired.wait(5)
    assert len(seen) == 1 and seen[0][1:] == ("flash", {"a": 1})
    assert q.resolve(seen[0][0], Decision.APPROVED)
    assert done.wait(5)
    assert out == [Decision.APPROVED] and len(seen) == 1


def test_callback_may_resolve_without_deadlock():
    def cb(entry):
        assert q.pending()  # lock not held: inspect works
        assert q.resolve(entry.id, Decision.DENIED)

    q = ApprovalQueue(timeout=5, on_pending=cb)
    out, done = [], threading.Event()
    _run(q, out, done)
    assert done.wait(5)
    assert out == [Decision.DENIED]


def test_no_hook_unchanged():
    q = ApprovalQueue(timeout=5)
    out, done = [], threading.Event()
    _run(q, out, done)
    while not q.pending():
        done.wait(0.01)
    assert q.resolve(q.pending()[0].id, Decision.APPROVED)
    assert done.wait(5) and out == [Decision.APPROVED]
