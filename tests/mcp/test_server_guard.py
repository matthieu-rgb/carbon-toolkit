# SPDX-License-Identifier: GPL-3.0-or-later
"""AC-10: a destructive tool over MCP blocks until a human approves it."""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
import time

import pytest
from mcp import Client

from carbon.core.execute import Decision, Origin, execute_tool
from carbon.core.session import Session
from carbon.emu.ecu import SimulatedEcu
from carbon.mcp.approval import ApprovalQueue, DenyingApprover
from carbon.mcp.server import build_mcp_server

_counter = itertools.count()


@pytest.fixture
def channel() -> str:
    return f"carbon-mcp-guard-{next(_counter)}"


@pytest.fixture
def ecu(channel):
    with SimulatedEcu(channel, interface="virtual") as e:
        assert e.ready.is_set()
        yield e


def _server(channel, tmp_path, approver):
    s = Session(channel=channel, interface="virtual",
                journal_path=tmp_path / "j.jsonl", approver=approver)
    return build_mcp_server(s)


def _unlock(server):
    assert _call(server, "uds_session", {"session": "extended"}).structured_content["ok"]
    assert _call(server, "uds_security_access", {"level": 1}).structured_content["ok"]


def _call(server, tool, args=None):
    async def run():
        async with Client(server) as client:
            return await client.call_tool(tool, args or {})

    return asyncio.run(run())


class _Worker:
    """Runs a (blocking) MCP call in its own thread with its own event loop."""

    def __init__(self, server, tool, args=None):
        self.result = None
        self.error = None
        self._t = threading.Thread(target=self._run, args=(server, tool, args), daemon=True)
        self._t.start()

    def _run(self, server, tool, args):
        try:
            self.result = _call(server, tool, args)
        except BaseException as exc:  # surfaced by join()
            self.error = exc

    def join(self, timeout=10.0):
        self._t.join(timeout)
        assert not self._t.is_alive(), "MCP call still blocked"
        assert self.error is None, self.error
        return self.result

    @property
    def done(self):
        return not self._t.is_alive()


def _wait_pending(queue, worker, deadline=10.0):
    """Bounded poll on queue.pending(); no fixed sleep."""
    gate = threading.Event()
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        p = queue.pending()
        if p:
            return p[0]
        assert worker.error is None, worker.error
        gate.wait(0.005)
    raise AssertionError("no pending approval appeared")


def _journal(tmp_path):
    p = tmp_path / "j.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]


def test_destructive_blocks_then_executes_on_approval(ecu, channel, tmp_path):
    queue = ApprovalQueue()
    server = _server(channel, tmp_path, queue)
    assert ecu._dtcs, "fixture ECU should hold DTCs"
    _unlock(server)
    w = _Worker(server, "uds_clear_dtc")
    pend = _wait_pending(queue, w)
    assert pend.tool == "uds_clear_dtc"
    assert not w.done  # blocked
    assert ecu._dtcs  # nothing executed yet
    assert queue.resolve(pend.id, Decision.APPROVED) is True
    r = w.join()
    assert r.structured_content["ok"] is True
    assert ecu._dtcs == []
    entries = [e for e in _journal(tmp_path) if e["tool"] == "uds_clear_dtc"]
    assert entries and entries[-1]["actor"] == "mcp" and entries[-1]["ok"] is True


def test_destructive_denied_is_refused(ecu, channel, tmp_path):
    queue = ApprovalQueue()
    server = _server(channel, tmp_path, queue)
    _unlock(server)
    before = list(ecu._dtcs)
    assert before
    w = _Worker(server, "uds_clear_dtc")
    pend = _wait_pending(queue, w)
    assert queue.resolve(pend.id, Decision.DENIED) is True
    r = w.join()
    assert r.structured_content["ok"] is False
    assert ecu._dtcs == before  # not executed
    still = _call(server, "uds_read_dtc")
    assert still.structured_content["ok"] is True
    entries = [e for e in _journal(tmp_path) if e["tool"] == "uds_clear_dtc"]
    assert entries and entries[-1]["ok"] is False and entries[-1]["actor"] == "mcp"


def test_server_responsive_while_destructive_pending(ecu, channel, tmp_path):
    queue = ApprovalQueue()
    server = _server(channel, tmp_path, queue)
    _unlock(server)
    w = _Worker(server, "uds_clear_dtc")
    pend = _wait_pending(queue, w)
    try:
        scan = _call(server, "uds_scan")  # must return, not freeze
        assert scan.structured_content["ok"] is True
        assert not w.done
        assert ecu._dtcs
    finally:
        queue.resolve(pend.id, Decision.DENIED)
        w.join()


def test_stdio_mode_refuses_destructive(ecu, channel, tmp_path):
    server = _server(channel, tmp_path, DenyingApprover())
    _unlock(server)
    w = _Worker(server, "uds_clear_dtc")
    r = w.join(timeout=5.0)  # immediate: no block
    sc = r.structured_content
    assert sc["ok"] is False
    assert "aucun canal d'approbation" in json.dumps(sc, ensure_ascii=False)
    assert ecu._dtcs


def test_destructive_timeout_is_refused(ecu, channel, tmp_path):
    queue = ApprovalQueue(timeout=0.2)
    server = _server(channel, tmp_path, queue)
    _unlock(server)
    before = list(ecu._dtcs)
    assert before
    r = _Worker(server, "uds_clear_dtc").join(timeout=10.0)  # nobody resolves it
    sc = r.structured_content
    assert sc["ok"] is False
    assert "timeout" in sc["summary"].lower()
    assert ecu._dtcs == before
    entries = [e for e in _journal(tmp_path) if e["tool"] == "uds_clear_dtc"]
    assert entries and entries[-1]["ok"] is False and entries[-1]["actor"] == "mcp"


@pytest.mark.parametrize("approver_factory", [DenyingApprover, lambda: ApprovalQueue(timeout=0.2)])
def test_assume_yes_has_no_effect_over_mcp(ecu, channel, tmp_path, approver_factory):
    """Over origin=MCP, assume_yes never executes without an APPROVED decision."""
    server = _server(channel, tmp_path, DenyingApprover())
    _unlock(server)  # ECU unlocked: only the guard stands between call and clear
    before = list(ecu._dtcs)
    assert before
    session = Session(channel=channel, interface="virtual",
                      journal_path=tmp_path / "j2.jsonl")
    adapter = session.registry.get("uds_clear_dtc")
    params = {"channel": channel, "interface": "virtual"}
    result = execute_tool(adapter, params, origin=Origin.MCP,
                          journal=session.journal, assume_yes=True,
                          approver=approver_factory())
    assert result.ok is False
    assert ecu._dtcs == before
