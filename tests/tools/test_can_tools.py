# SPDX-License-Identifier: GPL-3.0-or-later
import threading
import time

import pytest

from carbon.can.bus import open_bus, receive_frames, send_frame
from carbon.tools.can_dump import CanDump
from carbon.tools.can_inject import CanInject
from carbon.tools.can_replay import CanReplay
from carbon.tools.can_sniff import CanSniff

CH = "carbon_tools_test"


def _send_later(frames, delay=0.3):
    def work():
        time.sleep(delay)
        bus = open_bus(CH, interface="virtual")
        for arb, data, ext in frames:
            send_frame(bus, arb, data, ext)
        time.sleep(0.2)
        bus.shutdown()

    t = threading.Thread(target=work)
    t.start()
    return t


def test_sniff_returns_sent_frames():
    t = _send_later([(0x123, b"\x01\x02", False), (0x456, b"\xff", False)])
    res = CanSniff().run(channel=CH, interface="virtual", count=2, timeout=3.0)
    t.join()
    assert res.ok and res.tool == "can_sniff"
    ids = [f["arbitration_id"] for f in res.data["frames"]]
    assert ids == [0x123, 0x456]
    assert res.data["frames"][0]["data"] == "0102"
    assert "2" in res.summary


def test_dump_then_replay_roundtrip(tmp_path):
    traffic = [(0x123, b"\xde\xad\xbe\xef", False), (0x1ABCDE, b"", True), (0x7FF, b"\x00" * 8, False)]
    path = tmp_path / "cap.log"
    t = _send_later(traffic)
    res = CanDump().run(channel=CH, interface="virtual", path=str(path), count=3, timeout=3.0)
    t.join()
    assert res.artifacts == [str(path)]
    from carbon.tools.can_dump import parse_capture

    assert parse_capture(str(path)) == traffic

    obs = open_bus(CH, interface="virtual")
    try:
        rres = CanReplay().run(channel=CH, interface="virtual", path=str(path))
        got = receive_frames(obs, count=3, timeout=2.0)
    finally:
        obs.shutdown()
    assert rres.ok
    assert [(m.arbitration_id, bytes(m.data), m.is_extended_id) for m in got] == traffic


def test_inject_sends_frame():
    obs = open_bus(CH, interface="virtual")
    try:
        res = CanInject().run(channel=CH, interface="virtual", arb_id=0x100, data=[1, 2, 3])
        got = receive_frames(obs, count=1, timeout=2.0)
    finally:
        obs.shutdown()
    assert res.ok and bytes(got[0].data) == b"\x01\x02\x03"


def test_inject_invalid_id_raises():
    with pytest.raises(ValueError):
        CanInject().run(channel=CH, interface="virtual", arb_id=0x800, data=[1])
    with pytest.raises(ValueError):
        CanInject().run(channel=CH, interface="virtual", arb_id=0x20000000, data=[1], extended=True)


def test_inject_payload_too_long_raises():
    with pytest.raises(ValueError):
        CanInject().run(channel=CH, interface="virtual", arb_id=0x1, data=list(range(9)))


def test_inject_bad_byte_raises():
    with pytest.raises(ValueError):
        CanInject().run(channel=CH, interface="virtual", arb_id=0x1, data=[256])


def test_replay_empty_file_raises(tmp_path):
    p = tmp_path / "empty.log"
    p.write_text("\n")
    with pytest.raises(ValueError):
        CanReplay().run(channel=CH, interface="virtual", path=str(p))


def test_replay_corrupt_line_names_line(tmp_path):
    p = tmp_path / "bad.log"
    p.write_text("(1.000000) vcan0 123#AA\n(2.000000) vcan0 garbage\n")
    with pytest.raises(ValueError, match="line 2"):
        CanReplay().run(channel=CH, interface="virtual", path=str(p))


def test_destructive_flags():
    assert CanReplay.destructive and CanInject.destructive
    assert not CanSniff.destructive and not CanDump.destructive
