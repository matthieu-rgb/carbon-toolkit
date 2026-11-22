# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from tests.web.conftest import SseReader


def test_sse_emits_snapshot_on_connect(live):
    evs = live.sse(2)
    assert [e for e, _ in evs] == ["state", "pending"]
    assert {"tools", "surface", "methodology"} <= set(evs[0][1])
    assert evs[1][1] == []


def test_sse_emits_state_on_tool_run(live, ecu):
    r = SseReader(live)
    try:
        r.wait_for("state")
        n = len(r.events)
        assert live.post("/api/tool/uds_scan", json={}).json()["ok"] is True
        r.wait_for("state", start=n)
    finally:
        r.close()


def test_sse_heartbeat_ping_and_unsubscribes(live):
    import httpx
    with httpx.Client(base_url=live.base, cookies=live.cookies,
                      timeout=httpx.Timeout(5)) as c:
        with c.stream("GET", "/api/events") as resp:
            seen = False
            for line in resp.iter_lines():
                if line.startswith(": ping"):
                    seen = True
                    break
    assert seen
    import time
    end = time.monotonic() + 5
    while live.broker._subs and time.monotonic() < end:
        time.sleep(0.05)
    assert not live.broker._subs
