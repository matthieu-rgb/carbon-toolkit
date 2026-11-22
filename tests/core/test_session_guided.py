# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import itertools
import threading
from pathlib import Path

import pytest
from can.interfaces import virtual

from carbon.can.bus import open_bus, send_frame
from carbon.core.execute import Decision
from carbon.core.session import Session
from carbon.emu.ecu import SimulatedEcu
from carbon.mcp.approval import ApprovalQueue

TREE = Path(__file__).resolve().parents[2] / "carbon" / "methodology" / "trees" / "carbon_v1.yaml"
_counter = itertools.count()


@pytest.fixture
def channel() -> str:
    return f"carbon-guided-test-{next(_counter)}"


@pytest.fixture
def ecu(channel):
    with SimulatedEcu(channel, interface="virtual") as e:
        assert e.ready.is_set()
        yield e


def _approving_queue() -> ApprovalQueue:
    # Resolve from a worker thread as soon as the request is queued.
    q: ApprovalQueue | None = None

    def on_pending(entry):
        threading.Thread(target=lambda: q.resolve(entry.id, Decision.APPROVED)).start()

    q = ApprovalQueue(timeout=10.0, on_pending=on_pending)
    return q


def _session(channel, tmp_path, **kw):
    s = Session(channel=channel, interface="virtual",
                journal_path=tmp_path / "j.jsonl", **kw)
    s.load_methodology(TREE)
    return s


def _sniff_with_traffic(s: Session, channel: str):
    def work():
        bus = open_bus(channel, interface="virtual")
        import time
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
    r = s.run_tool("can_sniff", count=1, timeout=3.0)
    t.join()
    return r


def test_state_reflects_loaded_methodology(channel, tmp_path):
    s = _session(channel, tmp_path)
    m = s.state()["methodology"]
    assert m["loaded"] is True and m["mode"] == "guided"
    assert m["current"]["id"] == "acces"
    assert [c["id"] for c in m["candidates"]] == ["recon"]
    assert len(s.state()["tools"]) == 10


def test_guided_walk_end_to_end(ecu, channel, tmp_path):
    s = _session(channel, tmp_path, approver=_approving_queue())
    cur = lambda: s.engine.current_id  # noqa: E731
    s.step_ack()
    assert cur() == "recon"
    r = _sniff_with_traffic(s, channel)
    assert r.ok and r.data["frames"], r
    assert cur() == "uds_scan"
    assert s.run_tool("uds_scan").ok and cur() == "uds_session"
    assert s.run_tool("uds_session", session="extended").ok and cur() == "lire_dtc"
    assert s.run_tool("uds_read_dtc").ok and cur() == "seed_key"
    assert ecu._dtcs  # still present before unlock+clear
    assert s.run_tool("uds_security_access").ok and cur() == "effacer_dtc"
    assert ecu._dtcs
    r = s.run_tool("uds_clear_dtc")
    assert r.ok and r.data["cleared"] is True
    assert ecu._dtcs == [] and cur() == "rejeu"
    cap = tmp_path / "cap.log"
    cap.write_text("(0.0) vcan0 123#0102\n")
    r = s.run_tool("can_replay", path=str(cap))
    assert r.ok, r
    assert cur() == "injection"
    r = s.run_tool("can_inject", arb_id=0x123, data=[1])
    assert r.ok, r
    assert cur() == "injection"
    assert s.engine.satisfied is True


def test_guided_gate_blocks_out_of_step_tool(ecu, channel, tmp_path):
    s = _session(channel, tmp_path)
    s.step_ack()
    before = len(s.journal_text())
    r = s.run_tool("uds_clear_dtc")
    assert r.ok is False and "hors parcours" in r.summary
    assert ecu._dtcs and s.engine.current_id == "recon"
    assert len(s.journal_text()) == before and s.history == []

    s.set_mode("libre")
    r = s.run_tool("uds_scan")
    assert r.ok
    assert s.engine.history[-1]["tool"] == "uds_scan"
    assert s.engine.history[-1]["off_step"] is True
    assert s.engine.current_id == "recon"


def test_step_choose_and_ack(channel, tmp_path):
    s = _session(channel, tmp_path)
    s.step_ack()
    assert s.engine.current_id == "recon"
    with pytest.raises(ValueError):
        s.step_choose("injection")
    # recon has a single candidate (uds_scan): choose it explicitly
    s.step_choose("uds_scan")
    assert s.engine.current_id == "uds_scan"


def test_persist_and_resume_round_trip(ecu, channel, tmp_path):
    sp = tmp_path / "state.json"
    s = _session(channel, tmp_path, state_path=sp)
    s.step_ack()
    s.step_choose("uds_scan")
    assert s.run_tool("uds_scan").ok
    s.set_mode("libre")
    assert sp.exists()

    before = len(s.journal_text())
    r = Session.resume(sp, channel=channel, interface="virtual",
                       journal_path=tmp_path / "j2.jsonl")
    assert r.engine.current_id == "uds_session"
    assert r.mode == "libre"
    assert r.state()["methodology"]["current"]["id"] == "uds_session"
    assert r.journal_text() == "" and len(s.journal_text()) == before  # no ECU traffic
    assert r.engine.history == s.engine.history


def test_cli_open_guided_session_fresh_then_resume(channel, tmp_path):
    from carbon.cli import open_guided_session

    jp = tmp_path / "j.jsonl"
    sp = jp.with_suffix(".state.json")
    assert not sp.exists()
    s = open_guided_session(Session, TREE, channel=channel, interface="virtual",
                            journal_path=jp)  # fresh: persists to <journal>.state.json
    assert s.engine.current_id == "acces"
    s.step_ack()
    s.step_choose("uds_scan")
    s.set_mode("libre")
    assert sp.exists()

    r = open_guided_session(Session, TREE, channel=channel, interface="virtual",
                            journal_path=jp)  # state exists: resumed, not fresh
    assert r.engine.current_id == "uds_scan"
    assert r.mode == "libre"
    assert r.state_path == sp
    assert r.engine.history == s.engine.history
