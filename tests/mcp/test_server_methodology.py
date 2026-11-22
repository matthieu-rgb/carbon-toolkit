# SPDX-License-Identifier: GPL-3.0-or-later
"""Methodology/mode MCP tools drive the Session engine; the guard stays intact."""
from __future__ import annotations

import asyncio
import itertools
import threading
import time
from pathlib import Path

import pytest
from can.interfaces import virtual
from mcp import Client

from carbon.can.bus import open_bus, send_frame
from carbon.core.execute import Decision
from carbon.core.session import Session
from carbon.emu.ecu import SimulatedEcu
from carbon.mcp.approval import ApprovalQueue
from carbon.mcp.server import build_mcp_server

V1 = Path(__file__).resolve().parents[2] / "carbon" / "methodology" / "trees" / "carbon_v1.yaml"
_counter = itertools.count()


@pytest.fixture
def channel() -> str:
    return f"carbon-mcp-meth-{next(_counter)}"


@pytest.fixture
def ecu(channel):
    with SimulatedEcu(channel, interface="virtual") as e:
        assert e.ready.is_set()
        yield e


def _server(channel, tmp_path, approver=None):
    kw = {"approver": approver} if approver is not None else {}
    s = Session(channel=channel, interface="virtual",
                journal_path=tmp_path / "j.jsonl", **kw)
    return build_mcp_server(s)


def _call(server, tool, args=None):
    async def run():
        async with Client(server) as client:
            return await client.call_tool(tool, args or {})

    return asyncio.run(run())


def _meth(server):
    return _call(server, "session_state").structured_content["methodology"]


def test_load_shows_step_and_candidates(channel, tmp_path):
    server = _server(channel, tmp_path)
    assert _meth(server) == {"mode": "libre", "loaded": False}
    r = _call(server, "methodology_load", {"path": str(V1)})
    assert r.structured_content["methodology"]["loaded"] is True
    m = _meth(server)
    assert m["loaded"] is True and m["current"]["id"] == "acces"
    assert [c["id"] for c in m["candidates"]] == ["recon"]


def test_mode_set_round_trip(channel, tmp_path):
    server = _server(channel, tmp_path)
    _call(server, "methodology_load", {"path": str(V1)})
    assert _call(server, "mode_set", {"mode": "libre"}).structured_content["methodology"]["mode"] == "libre"
    assert _meth(server)["mode"] == "libre"
    _call(server, "mode_set", {"mode": "guided"})
    assert _meth(server)["mode"] == "guided"


def test_step_ack_advances_from_access(channel, tmp_path):
    server = _server(channel, tmp_path)
    _call(server, "methodology_load", {"path": str(V1)})
    r = _call(server, "step_ack")
    assert r.structured_content["methodology"]["current"]["id"] == "recon"
    assert _meth(server)["current"]["id"] == "recon"


def test_step_choose_resolves_candidate(channel, tmp_path):
    server = _server(channel, tmp_path)
    _call(server, "methodology_load", {"path": str(V1)})
    _call(server, "step_ack")
    m = _meth(server)
    assert m["current"]["id"] == "recon"
    assert [c["id"] for c in m["candidates"]] == ["uds_scan"]
    r = _call(server, "step_choose", {"step_id": "uds_scan"})
    assert r.structured_content["methodology"]["current"]["id"] == "uds_scan"


def test_bad_input_is_mcp_error(channel, tmp_path):
    server = _server(channel, tmp_path)
    assert _call(server, "step_ack").is_error  # nothing loaded
    _call(server, "methodology_load", {"path": str(V1)})
    assert _call(server, "mode_set", {"mode": "bogus"}).is_error
    assert _call(server, "step_choose", {"step_id": "nope"}).is_error


def test_tool_schemas_typed(channel, tmp_path):
    server = _server(channel, tmp_path)

    async def run():
        async with Client(server) as client:
            return {t.name: t for t in (await client.list_tools()).tools}

    tools = asyncio.run(run())
    for name, arg in [("methodology_load", "path"), ("mode_set", "mode"),
                      ("step_choose", "step_id")]:
        assert tools[name].input_schema["properties"][arg]["type"] == "string"
    assert tools["step_ack"].input_schema.get("properties", {}) == {}
    assert "session_state" in tools


def _sniff_with_traffic(server, channel):
    def work():
        bus = open_bus(channel, interface="virtual")
        end = time.monotonic() + 10
        while time.monotonic() < end:
            with virtual.channels_lock:
                if len(virtual.channels.get(channel, [])) >= 3:  # ecu + us + sniffer
                    break
            time.sleep(0.005)
        send_frame(bus, 0x123, b"\x01\x02", False)
        bus.shutdown()

    t = threading.Thread(target=work)
    t.start()
    r = _call(server, "can_sniff", {"count": 1, "timeout": 3.0})
    t.join()
    return r


def test_destructive_still_pending_in_guided_flow(ecu, channel, tmp_path):
    queue = ApprovalQueue()
    server = _server(channel, tmp_path, queue)
    _call(server, "methodology_load", {"path": str(V1)})
    assert _meth(server)["mode"] == "guided"
    _call(server, "step_ack")
    # Walk the guided path to the clear step (each tool must match the step).
    assert _sniff_with_traffic(server, channel).structured_content["ok"]
    for tool, args in [("uds_scan", {}),
                       ("uds_session", {"session": "extended"}), ("uds_read_dtc", {}),
                       ("uds_security_access", {"level": 1})]:
        r = _call(server, tool, args).structured_content
        assert r["ok"], (tool, r, _meth(server)["current"])
    assert _meth(server)["current"]["id"] == "effacer_dtc"
    box: dict = {}

    def worker():
        try:
            box["r"] = _call(server, "uds_clear_dtc")
        except BaseException as exc:
            box["e"] = exc

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    end, gate, pend = time.monotonic() + 10, threading.Event(), None
    while time.monotonic() < end and not pend:
        p = queue.pending()
        pend = p[0] if p else None
        assert "e" not in box, box.get("e")
        gate.wait(0.005)
    assert pend is not None and pend.tool == "uds_clear_dtc"
    assert t.is_alive() and ecu._dtcs  # blocked, nothing executed
    assert queue.resolve(pend.id, Decision.APPROVED) is True
    t.join(10)
    assert not t.is_alive() and "e" not in box
    assert box["r"].structured_content["ok"] is True
    assert ecu._dtcs == []
