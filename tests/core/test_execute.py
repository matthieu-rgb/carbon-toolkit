# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from carbon.core.adapter import Adapter
from carbon.core.execute import ActionRefused, Decision, Origin, execute_tool
from carbon.core.journal import Journal
from carbon.core.result import ToolResult


def _now():
    return datetime.now(timezone.utc)


def _ok(name):
    t = _now()
    return ToolResult(tool=name, ok=True, summary="done", started_at=t, ended_at=t, data={}, artifacts=[])


class Safe(Adapter):
    name = "safe"
    destructive = False

    def run(self, **params):
        return _ok(self.name)


class Danger(Adapter):
    name = "danger"
    destructive = True

    def __init__(self):
        self.ran = False

    def run(self, **params):
        self.ran = True
        return _ok(self.name)


class Boom(Adapter):
    name = "boom"
    destructive = False

    def run(self, **params):
        raise ValueError("boom")


class Stub:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def request(self, tool, params):
        self.calls.append((tool, params))
        return self.decision


def _lines(journal):
    if not journal.path.exists():
        return []
    return [json.loads(x) for x in journal.path.read_text().splitlines()]


@pytest.fixture
def journal(tmp_path):
    return Journal(tmp_path / "j.jsonl")


def test_cli_nondestructive_runs_and_journals(journal):
    r = execute_tool(Safe(), {}, origin=Origin.CLI, journal=journal)
    assert r.ok
    lines = _lines(journal)
    assert len(lines) == 1 and lines[0]["actor"] == "cli"


def test_cli_destructive_refused_raises_and_not_journaled(journal):
    a = Danger()
    with pytest.raises(ActionRefused):
        execute_tool(a, {}, origin=Origin.CLI, journal=journal, assume_yes=False, interactive=False)
    assert _lines(journal) == []
    assert not a.ran


def test_cli_destructive_yes_runs(journal):
    a = Danger()
    r = execute_tool(a, {}, origin=Origin.CLI, journal=journal, assume_yes=True)
    assert r.ok and a.ran
    assert len(_lines(journal)) == 1


def test_mcp_destructive_assume_yes_still_requires_approval(journal):
    a = Danger()
    r = execute_tool(a, {"data": b"\x01"}, origin=Origin.MCP, journal=journal,
                     assume_yes=True, approver=Stub(Decision.DENIED))
    assert not r.ok and not a.ran
    lines = _lines(journal)
    assert len(lines) == 1 and lines[0]["actor"] == "mcp"
    assert lines[0]["params"] == {"data": "01"}


def test_mcp_destructive_approved_runs(journal):
    a = Danger()
    stub = Stub(Decision.APPROVED)
    r = execute_tool(a, {}, origin=Origin.MCP, journal=journal, approver=stub)
    assert r.ok and a.ran
    assert stub.calls == [("danger", {})]
    assert _lines(journal)[0]["actor"] == "mcp"


def test_mcp_no_approver_is_denied(journal):
    a = Danger()
    r = execute_tool(a, {}, origin=Origin.MCP, journal=journal, approver=None)
    assert not r.ok and not a.ran
    assert len(_lines(journal)) == 1


def test_transport_error_becomes_failed_result_and_journaled(journal):
    r = execute_tool(Boom(), {}, origin=Origin.CLI, journal=journal)
    assert not r.ok and "failed:" in r.summary
    assert len(_lines(journal)) == 1
