# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import itertools
import json

import pytest

from carbon.core.session import Session
from carbon.emu.ecu import SimulatedEcu

_counter = itertools.count()


@pytest.fixture
def channel() -> str:
    return f"carbon-session-test-{next(_counter)}"


@pytest.fixture
def ecu(channel):
    with SimulatedEcu(channel, interface="virtual") as e:
        assert e.ready.is_set()
        yield e


def _session(channel, tmp_path, **kw):
    return Session(channel=channel, interface="virtual", journal_path=tmp_path / "j.jsonl", **kw)


def test_run_nondestructive_tool_against_simulated_ecu(ecu, channel, tmp_path):
    s = _session(channel, tmp_path)
    r = s.run_tool("uds_scan")
    assert r.ok is True
    assert r.data["supported"]
    assert len(s.history) == 1
    lines = [json.loads(x) for x in s.journal_text().splitlines()]
    assert lines and lines[-1]["actor"] == "mcp"


def test_channel_interface_injected_not_required_from_caller(ecu, channel, tmp_path):
    r = _session(channel, tmp_path).run_tool("uds_read_did", did=0xF190)
    assert r.ok is True


def test_state_reports_tools_and_libre_methodology(channel, tmp_path):
    st = _session(channel, tmp_path).state()
    assert st["methodology"] == {"mode": "libre", "loaded": False}
    assert len(st["tools"]) == 10
    assert st["channel"] == channel and st["interface"] == "virtual"


def test_journal_text_empty_before_any_run(channel, tmp_path):
    assert _session(channel, tmp_path).journal_text() == ""


def test_history_is_capped(ecu, channel, tmp_path):
    s = _session(channel, tmp_path, history_limit=2)
    results = [s.run_tool("uds_scan") for _ in range(3)]
    assert len(s.history) == 2
    assert s.history == results[1:]
