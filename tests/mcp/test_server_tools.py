# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import itertools
import json

import pytest
from mcp import Client

from carbon.core.session import Session
from carbon.emu.ecu import SimulatedEcu
from carbon.mcp.server import build_mcp_server

_counter = itertools.count()

TOOLS = {
    "can_sniff", "can_dump", "can_replay", "can_inject", "uds_scan",
    "uds_session", "uds_security_access", "uds_read_did", "uds_read_dtc",
    "uds_clear_dtc",
}
DESTRUCTIVE = {"can_replay", "can_inject", "uds_clear_dtc"}


@pytest.fixture
def channel() -> str:
    return f"carbon-mcp-test-{next(_counter)}"


@pytest.fixture
def ecu(channel):
    with SimulatedEcu(channel, interface="virtual") as e:
        assert e.ready.is_set()
        yield e


def _server(channel, tmp_path):
    s = Session(channel=channel, interface="virtual", journal_path=tmp_path / "j.jsonl")
    return build_mcp_server(s)


def _drive(server, fn):
    async def run():
        async with Client(server) as client:
            return await fn(client)

    return asyncio.run(run())


def test_lists_all_tools(channel, tmp_path):
    async def go(c):
        return (await c.list_tools()).tools

    tools = _drive(_server(channel, tmp_path), go)
    assert {t.name for t in tools} == TOOLS | {"session_state"}
    by = {t.name: t for t in tools}
    for name in DESTRUCTIVE:
        assert "destructive" in (by[name].description or "").lower()


def test_uds_scan_via_mcp_returns_supported_services(ecu, channel, tmp_path):
    r = _drive(_server(channel, tmp_path), lambda c: c.call_tool("uds_scan", {}))
    assert not r.is_error
    sc = r.structured_content
    assert sc["ok"] is True and sc["data"]["supported"]


def test_uds_read_did_default_vin(ecu, channel, tmp_path):
    r = _drive(_server(channel, tmp_path), lambda c: c.call_tool("uds_read_did", {}))
    sc = r.structured_content
    assert sc["ok"] is True
    assert sc["data"]["did"] == 0xF190


def test_session_state_tool(channel, tmp_path):
    r = _drive(_server(channel, tmp_path), lambda c: c.call_tool("session_state", {}))
    sc = r.structured_content
    assert sc["methodology"]["mode"] == "libre"
    assert len(sc["tools"]) == 10
    assert sc["channel"] == channel and sc["interface"] == "virtual"


def test_journal_resource_returns_raw_jsonl(ecu, channel, tmp_path):
    async def go(c):
        await c.call_tool("uds_scan", {})
        return await c.read_resource("carbon://journal")

    res = _drive(_server(channel, tmp_path), go)
    lines = [json.loads(x) for x in res.contents[0].text.splitlines()]
    assert lines and lines[-1]["actor"] == "mcp"


def test_tool_schema_hides_transport_params(channel, tmp_path):
    async def go(c):
        return (await c.list_tools()).tools

    by = {t.name: t for t in _drive(_server(channel, tmp_path), go)}
    for name in TOOLS:
        props = by[name].input_schema.get("properties", {})
        assert not {"rxid", "txid", "channel", "interface"} & set(props)
    assert "did" in by["uds_read_did"].input_schema["properties"]
