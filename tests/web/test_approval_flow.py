# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import threading
import time

from tests.web.conftest import SseReader


def _unlock(live):
    for tool, body in [("uds_session", {"session": "extended"}),
                       ("uds_security_access", {"level": 1})]:
        assert live.post(f"/api/tool/{tool}", json=body).json()["ok"], tool


def _bg_clear(live, box):
    def w():
        box["r"] = live.post("/api/tool/uds_clear_dtc", json={}).json()
    t = threading.Thread(target=w, daemon=True)
    t.start()
    return t


def _wait_pending(live):
    end = time.monotonic() + 10
    while time.monotonic() < end:
        p = live.queue.pending()
        if p:
            return p[0]
        time.sleep(0.01)
    raise AssertionError("no pending approval")


def test_destructive_approval_roundtrip(live, ecu):
    _unlock(live)
    assert ecu._dtcs
    rd = SseReader(live)
    try:
        rd.wait_for("state")
        box = {}
        t = _bg_clear(live, box)
        ev = rd.wait_for("approval")
        assert ev["tool"] == "uds_clear_dtc"
        listed = live.client().get("/api/approvals").json()
        assert [a["id"] for a in listed] == [ev["id"]]
        assert t.is_alive() and ecu._dtcs  # blocked, nothing executed
        r = live.post(f"/api/approvals/{ev['id']}", json={"decision": "approve"})
        assert r.json() == {"ok": True}
        t.join(10)
        assert box["r"]["ok"] is True and ecu._dtcs == []
        res = rd.wait_for("resolved")
        assert res["id"] == ev["id"] and res["decision"] == "approve"
    finally:
        rd.close()


def test_destructive_denied(live, ecu):
    _unlock(live)
    box = {}
    t = _bg_clear(live, box)
    p = _wait_pending(live)
    assert live.post(f"/api/approvals/{p.id}", json={"decision": "deny"}).status_code == 200
    t.join(10)
    assert box["r"]["ok"] is False and "denied" in box["r"]["summary"]
    assert ecu._dtcs  # not executed


def test_no_browser_times_out_closed(make_live, ecu):
    lv = make_live(approval_timeout=0.3)
    _unlock(lv)
    r = lv.post("/api/tool/uds_clear_dtc", json={}).json()
    assert r["ok"] is False and ecu._dtcs
    assert lv.queue.pending() == []


def test_reconnect_replays_pending(live, ecu):
    _unlock(live)
    box = {}
    t = _bg_clear(live, box)
    p = _wait_pending(live)
    evs = live.sse(2)
    assert evs[1][0] == "pending"
    assert [a["id"] for a in evs[1][1]] == [p.id]
    live.post(f"/api/approvals/{p.id}", json={"decision": "deny"})
    t.join(10)


def test_can_inject_requires_approval(live):
    box = {}

    def w():
        box["r"] = live.post("/api/tool/can_inject",
                             json={"arb_id": 0x123, "data_hex": "00"}).json()
    t = threading.Thread(target=w, daemon=True)
    t.start()
    p = _wait_pending(live)
    assert p.tool == "can_inject"
    live.post(f"/api/approvals/{p.id}", json={"decision": "deny"})
    t.join(10)
    assert box["r"]["ok"] is False
