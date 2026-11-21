# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

import logging

from carbon.emu.ecu import EcuConfig, SimulatedEcu
from carbon.tools.uds_scan import UdsScan
from carbon.tools.uds_security_access import UdsSecurityAccess
from carbon.tools.uds_session import UdsSession
from carbon.uds.seedkey import ExampleSeedKey


@pytest.fixture
def ecu_channel(request):
    """Run a SimulatedEcu on a per-test virtual channel; yield the channel."""
    channel = f"carbon-uds-{request.node.name}"
    with SimulatedEcu(channel, interface="virtual"):
        yield channel


def test_uds_scan_finds_supported_services(ecu_channel):
    res = UdsScan().run(channel=ecu_channel, interface="virtual")
    assert res.ok and res.tool == "uds_scan"
    for sid in ("0x10", "0x14", "0x19", "0x22", "0x27", "0x3e"):
        assert sid in res.data["supported"]
    assert "0x11" in res.data["unsupported"]
    assert set(res.data["supported"]).isdisjoint(res.data["unsupported"])
    assert str(len(res.data["supported"])) in res.summary


def test_uds_session_extended_ok(ecu_channel):
    res = UdsSession().run(channel=ecu_channel, interface="virtual", session="extended")
    assert res.ok and res.tool == "uds_session"
    assert res.data == {"session": "extended"}


def test_uds_session_default_ok(ecu_channel):
    res = UdsSession().run(channel=ecu_channel, interface="virtual", session="default")
    assert res.ok and res.data == {"session": "default"}


def test_security_access_unlocks(ecu_channel):
    res = UdsSecurityAccess().run(channel=ecu_channel, interface="virtual")
    assert res.ok and res.tool == "uds_security_access"
    assert res.data == {"unlocked": True, "seed": "11223344", "level": 1}


def test_security_access_wrong_algo_reports_nrc(request, caplog):
    channel = f"carbon-uds-{request.node.name}"
    cfg = EcuConfig(algo=ExampleSeedKey(mask=0x0F0F0F0F))  # diverges from client
    with SimulatedEcu(channel, interface="virtual", config=cfg):
        with caplog.at_level(logging.CRITICAL):
            res = UdsSecurityAccess().run(channel=channel, interface="virtual")
    assert not res.ok
    assert "0x35" in res.summary
    assert res.data["unlocked"] is False
