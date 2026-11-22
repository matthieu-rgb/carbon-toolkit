# SPDX-License-Identifier: GPL-3.0-or-later
"""Web API routes (state, tool run, approvals) behind the Task 4 guard.

Every state-changing route is POST: cookies are port-agnostic, so the guard's
Origin check (which only fires on unsafe methods) must cover all mutations.
"""
from __future__ import annotations

import json
import queue as _queue
import time
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.background import BackgroundTask
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from carbon.core.execute import Decision, Origin
from carbon.core.session import Session
from carbon.mcp.approval import ApprovalQueue
from carbon.web.events import Broker
from carbon.web.security import WebGuardMiddleware

_PLACEHOLDER = "<!doctype html><html><head><title>CARBON</title></head><body>CARBON web client</body></html>"

# name -> {body_field: (kind, required, run_tool_kwarg, choices)}; mirrors carbon.mcp.server.
_P = lambda kind, req=False, kw=None, choices=None: (kind, req, kw, choices)  # noqa: E731
_SCHEMAS: dict[str, dict[str, tuple]] = {
    "can_sniff": {"count": _P("int?"), "timeout": _P("num")},
    "can_dump": {"path": _P("str", True), "count": _P("int?"), "timeout": _P("num")},
    "can_replay": {"path": _P("str", True)},
    "can_inject": {"arb_id": _P("int", True), "data_hex": _P("str", kw="data"),
                   "extended": _P("bool")},
    "uds_scan": {},
    "uds_session": {"session": _P("str", choices=("default", "extended"))},
    "uds_security_access": {"level": _P("int")},
    "uds_read_did": {"did": _P("int")},
    "uds_read_dtc": {"status_mask": _P("int")},
    "uds_clear_dtc": {"group": _P("int")},
}


class _Bad(Exception):
    pass


def _check(kind: str, v: Any) -> bool:
    if kind == "int?" and v is None:
        return True
    if kind in ("int", "int?"):
        return isinstance(v, int) and not isinstance(v, bool)
    if kind == "num":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if kind == "str":
        return isinstance(v, str)
    if kind == "bool":
        return isinstance(v, bool)
    return False


def _validate(name: str, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise _Bad("body must be a JSON object")
    if "assume_yes" in body or "yes" in body:
        raise _Bad("assume_yes is not accepted")
    schema = _SCHEMAS[name]
    unknown = set(body) - set(schema)
    if unknown:
        raise _Bad(f"unknown params: {sorted(unknown)}")
    out: dict[str, Any] = {}
    for field, (kind, required, kw, choices) in schema.items():
        if field not in body:
            if required:
                raise _Bad(f"missing param: {field}")
            continue
        v = body[field]
        if not _check(kind, v):
            raise _Bad(f"param {field} must be {kind.rstrip('?')}")
        if choices is not None and v not in choices:
            raise _Bad(f"param {field} must be one of {list(choices)}")
        out[kw or field] = v
    return out


def _frame(etype: str, data: Any) -> str:
    return f"event: {etype}\ndata: {json.dumps(data, default=str)}\n\n"


def create_web_runtime(*, channel: str, interface: str, journal_path: Path,
                       token: str, port: int, approval_timeout: float = 300.0,
                       heartbeat: float = 15.0, **session_kwargs: Any):
    """Single place that wires broker <-> approval queue <-> session <-> app.

    Returns (app, session, queue, broker). The callbacks are only
    ``broker.publish`` (never raises): ``Session.on_change`` raising would
    propagate out of ``run_tool``.
    """
    broker = Broker()
    queue = ApprovalQueue(
        timeout=approval_timeout,
        on_pending=lambda p: broker.publish(
            {"type": "approval", "id": p.id, "tool": p.tool, "params": p.params}),
    )
    session = Session(channel=channel, interface=interface, journal_path=journal_path,
                      approver=queue, on_change=lambda: broker.publish({"type": "state"}),
                      **session_kwargs)
    app = build_web_app(session, broker, queue, token, port, heartbeat=heartbeat)
    return app, session, queue, broker


def build_web_app(session: Session, broker: Broker, queue: ApprovalQueue,
                  token: str, port: int, *, heartbeat: float = 15.0) -> Starlette:
    async def index(request: Request):
        return HTMLResponse(_PLACEHOLDER)

    async def state(request: Request):
        return JSONResponse(await run_in_threadpool(session.state))

    async def run_tool(request: Request):
        name = request.path_params["name"]
        if name not in _SCHEMAS:
            return JSONResponse({"error": f"unknown tool: {name}"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        try:
            params = _validate(name, body)
        except _Bad as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        result = await run_in_threadpool(
            lambda: session.run_tool(name, origin=Origin.WEB, **params))
        return JSONResponse(result.to_dict())

    async def approvals(request: Request):
        return JSONResponse([{"id": p.id, "tool": p.tool, "params": p.params}
                             for p in queue.pending()])

    async def resolve(request: Request):
        try:
            body = await request.json()
            decision = {"approve": Decision.APPROVED, "deny": Decision.DENIED}[body["decision"]]
        except Exception:
            return JSONResponse({"error": "body must be {decision: approve|deny}"},
                                status_code=400)
        if not queue.resolve(request.path_params["id"], decision):
            return JSONResponse({"error": "unknown or already resolved"}, status_code=409)
        broker.publish({"type": "resolved", "id": request.path_params["id"],
                        "decision": body["decision"]})
        return JSONResponse({"ok": True})

    async def events(request: Request):
        # Subscribe before the snapshot so no event is missed in between.
        sub = broker.subscribe()

        async def gen():
            try:
                snap = await run_in_threadpool(session.state)
                yield _frame("state", snap)
                yield _frame("pending", [{"id": p.id, "tool": p.tool, "params": p.params}
                                         for p in queue.pending()])
                last = time.monotonic()
                poll = max(0.05, min(0.5, heartbeat))
                while True:
                    try:
                        ev = await run_in_threadpool(sub.get, poll)
                    except _queue.Empty:
                        if time.monotonic() - last >= heartbeat:
                            last = time.monotonic()
                            yield ": ping\n\n"
                        continue
                    last = time.monotonic()
                    et = ev.get("type")
                    if et == "state":
                        yield _frame("state", await run_in_threadpool(session.state))
                    elif et in ("approval", "resolved"):
                        yield _frame(et, ev)
            finally:
                sub.unsubscribe()  # also runs on client disconnect (cancellation)

        return StreamingResponse(
            gen(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            background=BackgroundTask(sub.unsubscribe))

    return Starlette(routes=[
        Route("/", index, methods=["GET"]),
        Route("/api/state", state, methods=["GET"]),
        Route("/api/tool/{name}", run_tool, methods=["POST"]),
        Route("/api/events", events, methods=["GET"]),
        Route("/api/approvals", approvals, methods=["GET"]),
        Route("/api/approvals/{id}", resolve, methods=["POST"]),
    ], middleware=[Middleware(WebGuardMiddleware, token=token, port=port)])
