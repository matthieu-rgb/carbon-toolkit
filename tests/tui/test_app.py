# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless TUI tests: App.run_test() + Pilot over a Session on a virtual bus.

Async bodies are driven with asyncio.run (the project has no pytest-asyncio).
"""
from __future__ import annotations

import asyncio
import itertools
import threading
from pathlib import Path

import pytest
from can.interfaces import virtual
from click.testing import CliRunner

from carbon.can.bus import open_bus, send_frame
from carbon.cli import main
from carbon.core.session import Session
from carbon.emu.ecu import SimulatedEcu
from carbon.mcp.approval import ApprovalQueue
from carbon.tui import ApprovalModal, CarbonApp

TREE = Path(__file__).resolve().parents[2] / "carbon" / "methodology" / "trees" / "carbon_v1.yaml"
_counter = itertools.count()


@pytest.fixture
def channel() -> str:
    return f"carbon-tui-test-{next(_counter)}"


@pytest.fixture
def ecu(channel):
    with SimulatedEcu(channel, interface="virtual") as e:
        assert e.ready.is_set()
        yield e


def make_app(channel, tmp_path) -> CarbonApp:
    s = Session(channel=channel, interface="virtual", journal_path=tmp_path / "j.jsonl")
    s.load_methodology(TREE)
    app = CarbonApp(s)
    app.queue = s.approver = ApprovalQueue(timeout=10.0, on_pending=app.on_pending)
    return app


def cur(app) -> str:
    return app.session.state()["methodology"]["current"]["id"]


async def run_step(app, pilot) -> None:
    await pilot.press("r")
    await app.workers.wait_for_complete()
    await pilot.pause()


async def wait_modal(app, pilot) -> None:
    async def poll():
        while not isinstance(app.screen, ApprovalModal):
            await pilot.pause()
    await asyncio.wait_for(poll(), 10)


async def reach_clear_step(app, pilot) -> None:
    await pilot.press("a")
    assert cur(app) == "recon"
    # Traffic for can_sniff: a worker sends once all bus members are attached.
    def traffic():
        bus = open_bus(app.session.channel, interface="virtual")
        import time
        end = time.monotonic() + 10
        while time.monotonic() < end:
            with virtual.channels_lock:
                if len(virtual.channels.get(app.session.channel, [])) >= 3:
                    break
            time.sleep(0.005)
        send_frame(bus, 0x123, b"\x01\x02", False)
        bus.shutdown()
    t = threading.Thread(target=traffic)
    t.start()
    # can_sniff defaults (count/timeout) via the params field.
    await pilot.press("p")
    app.query_one("#params").value = "count=1 timeout=3.0"
    await pilot.press("enter")
    await app.workers.wait_for_complete()
    await pilot.pause()
    t.join()
    app.query_one("#params").value = ""
    assert cur(app) == "uds_scan"
    for expected in ("uds_session", "lire_dtc", "seed_key", "effacer_dtc"):
        await run_step(app, pilot)
        assert cur(app) == expected


def test_guided_view_shows_current_step(channel, tmp_path):
    async def body():
        app = make_app(channel, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            text = str(app.query_one("#step").render())
            assert "1. Accès physique" in text
            assert "Relier l'outil au bus" in text
    asyncio.run(body())


def test_run_current_tool_advances_engine(ecu, channel, tmp_path):
    async def body():
        app = make_app(channel, tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            assert cur(app) == "recon"
            await pilot.press("p")
            app.query_one("#params").value = "count=1 timeout=0.2"
            # no traffic: sniff fails -> engine must NOT advance, result is shown
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert cur(app) == "recon"
            assert app.last_result is not None
            assert "recon" in str(app.query_one("#status").render())
    asyncio.run(body())


def test_scan_steps_advance_after_traffic(ecu, channel, tmp_path):
    async def body():
        app = make_app(channel, tmp_path)
        async with app.run_test() as pilot:
            await reach_clear_step(app, pilot)
            assert "effacer_dtc" in str(app.query_one("#status").render())
    asyncio.run(body())


def test_destructive_approved_via_modal(ecu, channel, tmp_path):
    async def body():
        app = make_app(channel, tmp_path)
        async with app.run_test() as pilot:
            await reach_clear_step(app, pilot)
            assert ecu._dtcs
            await pilot.press("r")
            await wait_modal(app, pilot)
            assert "uds_clear_dtc" in str(app.screen.query_one("#approval-body").render())
            assert ecu._dtcs  # nothing executed before approval
            await pilot.click("#approve")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert ecu._dtcs == []
            assert cur(app) == "rejeu"
    asyncio.run(body())


def test_destructive_denied_via_modal(ecu, channel, tmp_path):
    async def body():
        app = make_app(channel, tmp_path)
        async with app.run_test() as pilot:
            await reach_clear_step(app, pilot)
            await pilot.press("r")
            await wait_modal(app, pilot)
            await pilot.press("n")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert ecu._dtcs
            assert cur(app) == "effacer_dtc"
            assert app.last_result is not None and app.last_result.ok is False
    asyncio.run(body())


def test_mode_toggle_keeps_position(channel, tmp_path):
    async def body():
        app = make_app(channel, tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("a")
            assert cur(app) == "recon"
            await pilot.press("m")
            assert app.session.mode == "libre" and cur(app) == "recon"
            assert "LIBRE" in str(app.query_one("#step").render())
            assert app.query_one("#tools").display
            await pilot.press("m")
            assert app.session.mode == "guided" and cur(app) == "recon"
    asyncio.run(body())


def test_cli_registers_tui_command():
    r = CliRunner().invoke(main, ["tui", "--help"])
    assert r.exit_code == 0 and "--methodology" in r.output
