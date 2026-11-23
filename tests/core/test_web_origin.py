# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from datetime import datetime, timezone

from carbon.core.adapter import Adapter
from carbon.core.execute import Decision, Origin
from carbon.core.result import ToolResult
from carbon.core.session import Session


class Danger(Adapter):
    name = "danger"
    destructive = True

    def __init__(self):
        self.ran = False

    def run(self, **params):
        self.ran = True
        t = datetime.now(timezone.utc)
        return ToolResult(tool=self.name, ok=True, summary="done", started_at=t,
                          ended_at=t, data={}, artifacts=[])


class DenyingApprover:
    def request(self, tool, params):
        return Decision.DENIED


class Quick(Danger):
    name = "quick"
    destructive = False


def _session(tmp_path, **kw):
    return Session(channel="x", interface="virtual",
                   journal_path=tmp_path / "j.jsonl", **kw)


def test_origin_web_value():
    assert Origin.WEB.value == "web"


def test_web_origin_destructive_still_gated(tmp_path):
    s = _session(tmp_path, approver=DenyingApprover())
    d = Danger()
    s.registry.register(d)
    r = s.run_tool("danger", origin=Origin.WEB, assume_yes=True)
    assert r.ok is False and d.ran is False


def test_run_tool_calls_on_change(tmp_path):
    calls = []
    s = _session(tmp_path, on_change=lambda: calls.append(len(s.history)))
    s.registry.register(Quick())
    s.run_tool("quick", origin=Origin.WEB)
    assert calls == [1]
