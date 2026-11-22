# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from carbon.core.surface import build_surface


def _r(tool, data, ok=True):
    return {"tool": tool, "ok": ok, "summary": "", "data": data, "artifacts": [],
            "started_at": "t", "ended_at": "t"}


def _ids(s, typ=None):
    return [n["id"] for n in s["nodes"] if typ is None or n["type"] == typ]


def _sniff(*arbs):
    return _r("can_sniff", {"frames": [
        {"timestamp": 0.0, "arbitration_id": a, "extended": False, "data": "00"}
        for a in arbs]})


def _scan(*svcs):
    return _r("uds_scan", {"supported": list(svcs), "unsupported": []})


def test_empty_history_has_bus_only():
    s = build_surface([], channel="can0")
    assert [n["id"] for n in s["nodes"]] == ["bus:can0"]
    assert s["edges"] == []
    assert s["current"] is None
    assert s["session"] == {"active": None, "unlocked": False}


def test_sniff_adds_ecu_nodes():
    s = build_surface([_sniff(0x123, 0x456, 0x123)], channel="can0")
    assert _ids(s, "ecu") == ["ecu:0x123", "ecu:0x456"]
    assert {"source": "bus:can0", "target": "ecu:0x123"} in s["edges"]
    assert {"source": "bus:can0", "target": "ecu:0x456"} in s["edges"]


def test_scan_adds_service_nodes():
    s = build_surface([_scan("0x27", "0x22")], channel="can0")
    assert _ids(s, "service") == ["svc:0x7e8:0x27", "svc:0x7e8:0x22"]
    for n in s["nodes"]:
        if n["type"] == "service":
            assert n["parent"] == "ecu:0x7e8"
    assert {"source": "ecu:0x7e8", "target": "svc:0x7e8:0x27"} in s["edges"]


def test_session_sets_active():
    ok = _r("uds_session", {"session": "extended"})
    bad = _r("uds_session", {"session": "programming", "nrc": "0x12"}, ok=False)
    assert build_surface([ok], channel="c")["session"]["active"] == "extended"
    assert build_surface([bad], channel="c")["session"]["active"] is None
    assert build_surface([ok, bad], channel="c")["session"]["active"] == "extended"


def test_failed_security_access_not_unlocked():
    bad = _r("uds_security_access", {"unlocked": False, "level": 1, "nrc": "0x35"},
             ok=False)
    s = build_surface([bad], channel="c")
    assert s["session"]["unlocked"] is False
    assert _ids(s, "level") == []
    weird = _r("uds_security_access", {"unlocked": False, "level": 1})
    assert build_surface([weird], channel="c")["session"]["unlocked"] is False
    good = _r("uds_security_access", {"unlocked": True, "level": 1, "seed": "aa"})
    s = build_surface([bad, good], channel="c")
    assert s["session"]["unlocked"] is True
    lvl = [n for n in s["nodes"] if n["type"] == "level"]
    assert [n["id"] for n in lvl] == ["level:0x7e8"]
    assert lvl[0]["state"] == "unlocked"


def test_monotonic_no_duplicate_nodes():
    s = build_surface([_scan("0x27", "0x22"), _scan("0x27", "0x22")], channel="c")
    ids = _ids(s)
    assert len(ids) == len(set(ids))
    assert _ids(s, "service") == ["svc:0x7e8:0x27", "svc:0x7e8:0x22"]
    assert len(s["edges"]) == len({(e["source"], e["target"]) for e in s["edges"]})


def test_current_is_last_successful():
    hist = [_scan("0x27")]
    assert build_surface(hist, channel="c")["current"] == "ecu:0x7e8"
    sec = _r("uds_security_access", {"unlocked": True, "level": 1, "seed": "aa"})
    assert build_surface(hist + [sec], channel="c")["current"] == "level:0x7e8"
    bad = _r("uds_session", {"session": "x", "nrc": "0x12"}, ok=False)
    assert build_surface(hist + [sec, bad], channel="c")["current"] == "level:0x7e8"
    assert build_surface([_sniff(0x1)], channel="c")["current"] == "bus:c"


def test_current_tool_override_and_dtcs():
    hist = [_scan("0x27"),
            _r("uds_read_dtc", {"dtcs": [{"code": "0x010203", "status": "0x08"}]})]
    s = build_surface(hist, channel="c")
    assert _ids(s, "dtc") == ["dtc:0x7e8:0x010203"]
    assert s["current"] == "ecu:0x7e8"
    assert build_surface(hist, channel="c", current_tool="can_sniff")["current"] == "bus:c"
    assert build_surface(hist, channel="c", current_tool="bogus")["current"] == "ecu:0x7e8"
