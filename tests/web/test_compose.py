# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from carbon.emu.ecu import SimulatedEcu
from carbon.web.serve import build_combined_app, serve_web

MCP_TOK, WEB_TOK = "mcp-tok", "web-tok"


@pytest.fixture
def combined(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app, session, queue, _ = build_combined_app(
        channel="compose-ch", interface="virtual", journal_path=tmp_path / "j.jsonl",
        web_token=WEB_TOK, mcp_token=MCP_TOK, port=port)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    end = time.monotonic() + 10
    while not server.started and time.monotonic() < end:
        time.sleep(0.02)
    assert server.started
    yield port, session, queue
    server.should_exit = True
    t.join(10)


def test_mcp_route_still_requires_bearer(combined):
    port, *_ = combined
    r = httpx.post(f"http://127.0.0.1:{port}/mcp", content="{}")
    assert r.status_code == 401
    r = httpx.post(f"http://127.0.0.1:{port}/mcp", content="{}",
                   headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    # Web unaffected by the MCP guard: no cookie -> its own guard answers
    assert httpx.get(f"http://127.0.0.1:{port}/api/state").status_code == 401


def test_mcp_prefix_boundary_exact(combined):
    port, *_ = combined
    b = f"http://127.0.0.1:{port}"
    # sub-path of /mcp -> MCP Bearer guard
    r = httpx.get(f"{b}/mcp/anything")
    assert r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer"
    # cookie must not satisfy MCP
    r = httpx.post(f"{b}/mcp", content="{}", cookies={"carbon_web": WEB_TOK})
    assert r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer"
    # look-alike prefixes go to the WEB guard, never MCP
    for path in ("/mcpevil", "/mcp.x", "/mcp-x/y"):
        r = httpx.get(f"{b}{path}")
        assert r.status_code == 401
        assert "www-authenticate" not in r.headers and r.headers.get("cache-control") == "no-store"
        # with the web cookie it reaches the web app (404), proving it is not MCP
        r = httpx.get(f"{b}{path}", cookies={"carbon_web": WEB_TOK})
        assert r.status_code == 404


def test_web_route_requires_cookie_not_bearer(combined):
    port, *_ = combined
    r = httpx.get(f"http://127.0.0.1:{port}/api/state",
                  headers={"Authorization": f"Bearer {MCP_TOK}"})
    assert r.status_code == 401
    r = httpx.get(f"http://127.0.0.1:{port}/api/state", cookies={"carbon_web": WEB_TOK})
    assert r.status_code == 200


def test_shared_session_web_and_mcp(combined):
    port, session, queue = combined
    base = f"http://127.0.0.1:{port}"
    with SimulatedEcu("compose-ch", interface="virtual") as ecu:
        assert ecu.ready.is_set()
        r = httpx.post(f"{base}/api/tool/uds_scan", json={}, headers={"Origin": base},
                       cookies={"carbon_web": WEB_TOK}, timeout=15)
        assert r.status_code == 200
    st = httpx.get(f"{base}/api/state", cookies={"carbon_web": WEB_TOK}).json()
    assert st == session.state()

    async def go():
        c = create_mcp_http_client(headers={"Authorization": f"Bearer {MCP_TOK}"})
        async with c:
            async with Client(streamable_http_client(f"{base}/mcp", http_client=c)) as cl:
                return await cl.call_tool("session_state", {})

    res = asyncio.run(go())
    assert not res.is_error
    # MCP's view must equal the shared Session's (incl. the Web-run tool in history).
    import json
    mcp_state = res.structured_content or json.loads(res.content[0].text)
    assert mcp_state == json.loads(json.dumps(session.state(), default=str))
    assert "uds_scan" in json.dumps(mcp_state)
    assert session.approver is queue


def test_serve_web_rejects_non_localhost_bind(tmp_path):
    with pytest.raises(ValueError):
        serve_web(channel="x", interface="virtual", journal_path=tmp_path / "j",
                  host="0.0.0.0", port=8800)


def test_build_combined_app_accepts_state_path_override(tmp_path):
    app, session, _, _ = build_combined_app(
        channel="compose-ch", interface="virtual", journal_path=tmp_path / "j.jsonl",
        web_token=WEB_TOK, mcp_token=MCP_TOK, port=8799,
        state_path=tmp_path / "custom.state.json")
    assert app is not None
