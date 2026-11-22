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
from carbon.emu.ecu import SimulatedEcu
from carbon.mcp.transport import build_http_app, verify_token, write_token

REPO = Path(__file__).resolve().parents[2]


def test_verify_token():
    assert verify_token("Bearer s3cret", "s3cret")
    assert verify_token("bearer s3cret", "s3cret")
    assert not verify_token(None, "s3cret")
    assert not verify_token("", "s3cret")
    assert not verify_token("Bearer wrong", "s3cret")
    assert not verify_token("Basic s3cret", "s3cret")
    assert not verify_token("Bearer ", "s3cret")


@pytest.mark.parametrize("env", ["XDG_RUNTIME_DIR", "TMPDIR"])
def test_token_not_written_inside_repo(monkeypatch, tmp_path, env):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv(env, str(tmp_path))
    monkeypatch.setattr(transport.tempfile, "tempdir", None)
    p = write_token("abc")
    assert p.read_text() == "abc"
    assert not p.resolve().is_relative_to(REPO)


def test_token_file_fresh_and_private(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    # An attacker-planted predictable file/symlink is never reused or followed.
    victim = tmp_path / "victim"
    victim.write_text("keep")
    (tmp_path / f"carbon-mcp-token-{__import__('os').getpid()}").symlink_to(victim)
    p1, p2 = write_token("t1"), write_token("t2")
    assert p1 != p2 and not p1.is_symlink()
    assert p1.stat().st_mode & 0o777 == 0o600
    assert victim.read_text() == "keep"


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
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/nope")  # every route is guarded, not only /mcp
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
    """serve(stdio) builds the REAL server; a destructive call is really refused."""
    holder = {}
    real_build = transport.build_mcp_server

    def spy(session):
        server = real_build(session)
        holder["session"], holder["server"] = session, server

        async def noop():
            return None

        server.run_stdio_async = noop
        return server

    monkeypatch.setattr(transport, "build_mcp_server", spy)
    transport.serve(transport="stdio", channel="tr-stdio", interface="virtual",
                    journal_path=tmp_path / "j.jsonl")
    assert isinstance(holder["session"].approver, DenyingApprover)

    async def go():
        async with Client(holder["server"]) as c:
            return await c.call_tool("uds_clear_dtc", {})

    with SimulatedEcu("tr-stdio", interface="virtual") as ecu:
        assert ecu.ready.is_set()
        res = asyncio.run(go())
        assert res.structured_content["ok"] is False
        assert "aucun canal d'approbation" in str(res.structured_content)
        assert ecu._dtcs
