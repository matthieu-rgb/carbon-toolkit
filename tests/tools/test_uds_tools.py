# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from carbon.emu.ecu import SimulatedEcu
from carbon.tools.uds_scan import UdsScan


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
