# SPDX-License-Identifier: GPL-3.0-or-later
"""`carbon mcp serve`: stdio or HTTP (Bearer token) transport around build_mcp_server.

No new execution path: this only selects the transport and wires the approver.
SDK 2.3.0: ``MCPServer.run_stdio_async()`` / ``streamable_http_app()`` (Starlette,
served here with uvicorn). The SDK's own auth is OAuth-resource-server oriented
(issuer URL); a static local Bearer token is enforced by a small ASGI middleware.
"""
from __future__ import annotations

import asyncio
import atexit
import hmac
import os
import secrets
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from carbon.core.session import Session
from carbon.mcp.approval import ApprovalQueue, DenyingApprover, console_resolve
from carbon.mcp.server import build_mcp_server


def write_token(token: str) -> Path:
    """Write the token to a fresh, randomly named 0600 file (mkstemp: O_EXCL)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    fd, name = tempfile.mkstemp(prefix="carbon-mcp-token-", dir=base)
    with os.fdopen(fd, "w") as fh:
        fh.write(token)
    return Path(name)


def verify_token(header: str | None, token: str) -> bool:
    """True iff ``header`` is ``Bearer <token>`` (constant-time compare)."""
    if not header:
        return False
    scheme, _, supplied = header.partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        return False
    return hmac.compare_digest(supplied.strip().encode(), token.encode())


class BearerAuthMiddleware:
    """Pure ASGI middleware: 401 on every HTTP request lacking the right token."""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self._token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":  # websocket or anything else: never unauthenticated
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        supplied = headers.get(b"authorization", b"").decode("latin-1")
        if not verify_token(supplied, self._token):
            body = b'{"error":"unauthorized"}'
            await send({
                "type": "http.response.start", "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def build_http_app(session: Session, token: str):
    """Streamable-HTTP Starlette app guarded by the Bearer token."""
    app = build_mcp_server(session).streamable_http_app()
    return BearerAuthMiddleware(app, token)


def _console_loop(queue: ApprovalQueue) -> None:
    for line in sys.stdin:
        console_resolve(queue, line)


def serve(
    *, transport: str, channel: str, interface: str, journal_path: Path,
    host: str = "127.0.0.1", port: int = 8777,
) -> None:
    if transport == "stdio":
        session = Session(
            channel=channel, interface=interface, journal_path=journal_path,
            approver=DenyingApprover(),
        )
        asyncio.run(build_mcp_server(session).run_stdio_async())
        return
    if transport != "http":
        raise ValueError(f"unknown transport {transport!r}")
    if host != "127.0.0.1":
        raise ValueError("HTTP transport binds 127.0.0.1 only")

    import uvicorn

    token = secrets.token_urlsafe(32)
    path = write_token(token)
    atexit.register(path.unlink, missing_ok=True)
    queue = ApprovalQueue()
    session = Session(
        channel=channel, interface=interface, journal_path=journal_path, approver=queue,
    )
    threading.Thread(target=_console_loop, args=(queue,), daemon=True).start()
    print(f"CARBON MCP on http://{host}:{port}/mcp ; Bearer token file: {path}", flush=True)
    print("Approvals: type 'list', 'approve <id>' or 'deny <id>' here.", flush=True)
    uvicorn.run(build_http_app(session, token), host=host, port=port, log_level="warning")
