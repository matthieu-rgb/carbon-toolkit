# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import http.client
import socket
import threading
from pathlib import Path

import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from carbon.core.session import Session
from carbon.mcp import transport
from carbon.mcp.approval import DenyingApprover
from carbon.mcp.transport import build_http_app, token_path, verify_token

REPO = Path(__file__).resolve().parents[2]


def test_verify_token():
    assert verify_token("Bearer s3cret", "s3cret")
    assert verify_token("bearer s3cret", "s3cret")
    assert not verify_token(None, "s3cret")
    assert not verify_token("", "s3cret")
    assert not verify_token("Bearer wrong", "s3cret")
    assert not verify_token("Basic s3cret", "s3cret")
    assert not verify_token("Bearer ", "s3cret")


def test_token_not_written_inside_repo():
    assert not token_path().resolve().is_relative_to(REPO)


@pytest.fixture
def http_server(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    session = Session(channel="x", interface="virtual", journal_path=tmp_path / "j.jsonl",
                      approver=DenyingApprover())
    app = build_http_app(session, "tok-123")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    gate = threading.Event()
    for _ in range(200):  # bounded readiness poll (<= ~10 s)
        if server.started:
            break
        gate.wait(0.05)
    assert server.started
    yield port
    server.should_exit = True
    t.join(timeout=10)


def test_http_requires_bearer_token(http_server):
    port = http_server
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/mcp", body="{}", headers={"Content-Type": "application/json"})
    assert conn.getresponse().status == 401
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/mcp", body="{}", headers={
        "Content-Type": "application/json", "Authorization": "Bearer nope"})
    assert conn.getresponse().status == 401

    async def go():
        from mcp.client.streamable_http import create_mcp_http_client
        http_client = create_mcp_http_client(headers={"Authorization": "Bearer tok-123"})
        async with http_client:
            async with Client(streamable_http_client(
                    f"http://127.0.0.1:{port}/mcp", http_client=http_client)) as c:
                return await c.call_tool("session_state", {})

    res = asyncio.run(go())
    assert not res.is_error


def test_stdio_session_uses_denying_approver(monkeypatch, tmp_path):
    seen = {}

    class FakeServer:
        async def run_stdio_async(self):
            return None

    def fake_build(session):
        seen["approver"] = session.approver
        seen["session"] = session
        return FakeServer()

    monkeypatch.setattr(transport, "build_mcp_server", fake_build)
    transport.serve(transport="stdio", channel="x", interface="virtual",
                    journal_path=tmp_path / "j.jsonl")
    assert isinstance(seen["approver"], DenyingApprover)
