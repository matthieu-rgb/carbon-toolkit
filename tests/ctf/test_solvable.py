# SPDX-License-Identifier: GPL-3.0-or-later
"""Every shipped challenge is solvable with CARBON's own tools, and the flag a
player would derive from the real tool output validates. This pins the flags to
the simulated ECU: if a tool's output or the ECU changes, these break."""
from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from carbon.core.execute import Origin
from carbon.core.session import Session
from carbon.ctf.catalog import bundled_challenges
from carbon.ctf.model import check_flag
from carbon.emu.ecu import SimulatedEcu
from carbon.uds.seedkey import ExampleSeedKey

_counter = itertools.count()


@pytest.fixture
def session(tmp_path):
    ch = f"ctf-solve-{next(_counter)}"
    with SimulatedEcu(ch, interface="virtual"):
        yield Session(channel=ch, interface="virtual", journal_path=tmp_path / "j.jsonl")


def _by_id():
    return {c.id: c for c in bundled_challenges()}


def test_recon_sec_service(session):
    supported = session.run_tool("uds_scan", origin=Origin.CLI).data["supported"]
    assert "0x27" in supported
    assert check_flag(_by_id()["recon-sec-service"], "CARBON{0x27}")


def test_read_vin(session):
    value = session.run_tool("uds_read_did", did=0xF190, origin=Origin.CLI).data["value"]
    vin = bytes.fromhex(value).decode("ascii")
    assert check_flag(_by_id()["read-vin"], f"CARBON{{{vin}}}")


def test_dump_dtcs(session):
    dtcs = session.run_tool("uds_read_dtc", origin=Origin.CLI).data["dtcs"]
    codes = ",".join(d["code"].replace("0x", "") for d in dtcs)
    assert check_flag(_by_id()["dump-dtcs"], f"CARBON{{{codes}}}")


def test_unlock_protected(session):
    # locked read is refused...
    denied = session.run_tool("uds_read_did", did=0x1234, origin=Origin.CLI)
    assert denied.ok is False
    # ...until session + security access
    session.run_tool("uds_session", origin=Origin.CLI)
    session.run_tool("uds_security_access", origin=Origin.CLI)
    value = session.run_tool("uds_read_did", did=0x1234, origin=Origin.CLI).data["value"]
    assert check_flag(_by_id()["unlock-protected"], f"CARBON{{{value}}}")


def test_seed_key_algo():
    key = ExampleSeedKey().key_from_seed(bytes.fromhex("11223344")).hex()
    assert check_flag(_by_id()["seed-key-algo"], f"CARBON{{{key}}}")
