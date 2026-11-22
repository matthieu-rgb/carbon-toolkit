# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import itertools

import pytest
from starlette.testclient import TestClient

from carbon.core.execute import Decision
from carbon.core.session import Session
from carbon.emu.ecu import SimulatedEcu
from carbon.mcp.approval import ApprovalQueue
from carbon.web.app import build_web_app
from carbon.web.events import Broker
from carbon.web.security import new_web_token

PORT = 8781
_counter = itertools.count()


@pytest.fixture
def channel() -> str:
    return f"carbon-web-api-{next(_counter)}"


@pytest.fixture
def ecu(channel):
    with SimulatedEcu(channel, interface="virtual") as e:
        assert e.ready.is_set()
        yield e


@pytest.fixture
def env(channel, tmp_path):
    queue = ApprovalQueue(timeout=1.0)
    s = Session(channel=channel, interface="virtual",
                journal_path=tmp_path / "j.jsonl", approver=queue)
    token = new_web_token()
    app = build_web_app(s, Broker(), queue, token, PORT)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}", follow_redirects=False)
    c.cookies.set("carbon_web", token)
    return c, queue, s


def _post(c, url, **kw):
    return c.post(url, headers={"Origin": f"http://127.0.0.1:{PORT}"}, **kw)


def test_root_requires_cookie_and_serves_html(env):
    c, _, _ = env
    assert "<html" in c.get("/").text.lower()
    c.cookies.clear()
    assert c.get("/").status_code == 401


def test_state_route_returns_surface(env):
    c, _, _ = env
    d = c.get("/api/state").json()
    assert {"tools", "surface", "methodology"} <= set(d)


def test_run_nondestructive_tool(env, ecu):
    c, _, _ = env
    r = _post(c, "/api/tool/uds_scan", json={})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True and "supported" in j["data"]


def test_run_unknown_tool_404(env):
    c, _, _ = env
    assert _post(c, "/api/tool/nope", json={}).status_code == 404


def test_run_rejects_assume_yes(env, ecu):
    c, queue, s = env
    n = len(s.history)
    r = _post(c, "/api/tool/uds_clear_dtc", json={"assume_yes": True})
    assert r.status_code == 400
    assert len(s.history) == n


def test_bad_params_400(env):
    c, _, _ = env
    assert _post(c, "/api/tool/uds_session", json={"session": "bogus"}).status_code == 400
    assert _post(c, "/api/tool/uds_session", json={"session": 3}).status_code == 400
    assert _post(c, "/api/tool/uds_session", json={"extra": 1}).status_code == 400
    assert _post(c, "/api/tool/can_inject", json={"data_hex": "00"}).status_code == 400  # arb_id missing
    assert _post(c, "/api/tool/uds_security_access", json={"level": True}).status_code == 400
    assert _post(c, "/api/tool/uds_scan", content=b"[1]").status_code == 400
    assert _post(c, "/api/tool/uds_scan", content=b"{bad").status_code == 400


def test_tool_route_is_post_only(env):
    c, _, _ = env
    assert c.get("/api/tool/uds_scan").status_code == 405


def test_domain_failure_is_200_ok_false(env, ecu):
    c, _, _ = env
    r = _post(c, "/api/tool/uds_session", json={"session": "default"})
    assert r.status_code == 200 and "ok" in r.json()


def test_approvals_list_empty(env):
    c, _, _ = env
    assert c.get("/api/approvals").json() == []


def test_approvals_resolve(env):
    c, queue, _ = env
    import threading
    out = []
    t = threading.Thread(target=lambda: out.append(queue.request("can_inject", {"arb_id": 1})))
    t.start()
    import time
    for _ in range(100):
        if queue.pending():
            break
        time.sleep(0.01)
    items = c.get("/api/approvals").json()
    assert items[0]["tool"] == "can_inject" and items[0]["params"] == {"arb_id": 1}
    aid = items[0]["id"]
    assert _post(c, f"/api/approvals/{aid}", json={"decision": "maybe"}).status_code == 400
    assert _post(c, f"/api/approvals/{aid}", json={"decision": "approve"}).status_code == 200
    t.join(2)
    assert out == [Decision.APPROVED]
    assert _post(c, f"/api/approvals/{aid}", json={"decision": "approve"}).status_code == 409
    assert _post(c, "/api/approvals/zzzz", json={"decision": "deny"}).status_code == 409


def test_state_tool_specs_match_destructive_gate(env):
    c, _, _ = env
    d = c.get("/api/state").json()
    spec = {t["name"]: t["destructive"] for t in d["tool_specs"]}
    for n in ("uds_clear_dtc", "can_inject", "can_replay"):
        assert spec[n] is True
    for n in ("uds_session", "uds_security_access", "uds_scan"):
        assert spec[n] is False
    assert d["tools"] == [t["name"] for t in d["tool_specs"]]
