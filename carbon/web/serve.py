# SPDX-License-Identifier: GPL-3.0-or-later
"""`carbon web`: one process, one Session, one ApprovalQueue; MCP + Web composed.

``/mcp`` is the Bearer-guarded MCP app; everything else is the cookie-guarded Web
app (WebGuardMiddleware lives inside the web app only, so the two token domains
never mix). The MCP console stdin loop is NOT started: the Web is the approval
surface.

Capacity note (Task 6 review): each open SSE stream and each blocked destructive
POST (waiting for approval) occupies one slot of the anyio 40-token threadpool
limiter. Fine for a single localhost operator; not a multi-user design.
"""
from __future__ import annotations

import atexit
import secrets
from pathlib import Path
from typing import Any

from carbon.mcp.server import build_mcp_server
from carbon.mcp.transport import build_mcp_sub_app, write_token
from carbon.web.app import create_web_runtime
from carbon.web.security import new_web_token, write_web_token

MCP_PREFIX = "/mcp"


class CombinedApp:
    """Minimal ASGI dispatcher: ``/mcp`` (exact or sub-path) -> MCP, else Web.

    The MCP sub-app keeps its own ``/mcp`` route, so the path is forwarded
    unchanged (a Starlette Mount would strip the prefix and 307 ``/mcp`` -> ``/mcp/``).
    Lifespan goes to the MCP app, which owns the streamable-HTTP session manager.
    """

    def __init__(self, web_app: Any, mcp_app: Any) -> None:
        self.web_app = web_app
        self.mcp_app = mcp_app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            await self.mcp_app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == MCP_PREFIX or path.startswith(MCP_PREFIX + "/"):
            await self.mcp_app(scope, receive, send)
        else:
            await self.web_app(scope, receive, send)


def build_combined_app(*, channel: str, interface: str, journal_path: Path,
                       web_token: str, mcp_token: str, port: int, **kw: Any):
    """Returns (app, session, queue, broker)."""
    kw.setdefault("state_path", journal_path.with_suffix(".state.json"))
    web_app, session, queue, broker = create_web_runtime(
        channel=channel, interface=interface, journal_path=journal_path,
        token=web_token, port=port, **kw)
    mcp_app = build_mcp_sub_app(session, mcp_token)
    return CombinedApp(web_app, mcp_app), session, queue, broker


def serve_web(*, channel: str, interface: str, journal_path: Path,
              host: str = "127.0.0.1", port: int = 8800) -> None:
    if host != "127.0.0.1":
        raise ValueError("carbon web binds 127.0.0.1 only")
    import uvicorn

    web_token = new_web_token()
    mcp_token = secrets.token_urlsafe(32)
    web_path = write_web_token(web_token)
    mcp_path = write_token(mcp_token)
    for p in (web_path, mcp_path):
        atexit.register(p.unlink, missing_ok=True)
    app, *_ = build_combined_app(
        channel=channel, interface=interface, journal_path=journal_path,
        web_token=web_token, mcp_token=mcp_token, port=port)
    print(f"CARBON web: open http://{host}:{port}/?k={web_token}  (one-time link)", flush=True)
    print(f"CARBON MCP on http://{host}:{port}/mcp ; Bearer token file: {mcp_path}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")
