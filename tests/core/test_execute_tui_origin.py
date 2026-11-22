# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from carbon.core.adapter import Adapter
from carbon.core.execute import Decision, Origin, execute_tool
from carbon.core.journal import Journal
from carbon.core.result import ToolResult


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


class Stub:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def request(self, tool, params):
        self.calls.append((tool, params))
        return self.decision


@pytest.fixture
def journal(tmp_path):
    return Journal(tmp_path / "j.jsonl")


def _lines(journal):
    return [json.loads(x) for x in journal.path.read_text().splitlines()]


def test_tui_value():
    assert Origin.TUI.value == "tui"


def test_tui_approved_runs_and_journals_tui(journal):
    a, ap = Danger(), Stub(Decision.APPROVED)
    r = execute_tool(a, {"x": 1}, origin=Origin.TUI, journal=journal, assume_yes=True, approver=ap)
    assert r.ok and a.ran and ap.calls == [("danger", {"x": 1})]
    assert [l["actor"] for l in _lines(journal)] == ["tui"]


def test_tui_denied_not_executed(journal):
    a = Danger()
    r = execute_tool(a, {}, origin=Origin.TUI, journal=journal, assume_yes=True,
                     approver=Stub(Decision.DENIED))
    assert not r.ok and not a.ran
    assert [l["actor"] for l in _lines(journal)] == ["tui"]


def test_tui_no_approver_denied_despite_assume_yes(journal):
    a = Danger()
    r = execute_tool(a, {}, origin=Origin.TUI, journal=journal, assume_yes=True)
    assert not r.ok and not a.ran
    assert [l["actor"] for l in _lines(journal)] == ["tui"]
