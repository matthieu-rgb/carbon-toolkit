# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from carbon.can.bus import BusUnavailableError, open_bus, receive_frames, send_frame


@pytest.fixture
def buses():
    a = open_bus("carbon_test", interface="virtual")
    b = open_bus("carbon_test", interface="virtual")
    yield a, b
    a.shutdown()
    b.shutdown()


def test_send_receive_over_virtual(buses):
    a, b = buses
    send_frame(a, 0x123, b"\x01\x02\x03")
    frames = receive_frames(b, count=1, timeout=1.0)
    assert len(frames) == 1
    assert frames[0].arbitration_id == 0x123
    assert bytes(frames[0].data) == b"\x01\x02\x03"
    assert frames[0].is_extended_id is False


def test_receive_timeout_returns_empty(buses):
    _, b = buses
    assert receive_frames(b, count=1, timeout=0.1) == []


def test_open_unknown_interface_raises_bus_unavailable():
    with pytest.raises(BusUnavailableError) as ei:
        open_bus("can0", interface="nonexistent_iface")
    assert "can0" in str(ei.value)
