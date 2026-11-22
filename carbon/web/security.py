# SPDX-License-Identifier: GPL-3.0-or-later
"""Web client security layer (spec §5.8 / §5.8.1 items 3-4).

Model
-----
* A dedicated **Web token** (never the MCP token) is generated at launch and stored
  outside the repo (``write_web_token``: mkstemp, O_EXCL, 0600).
* **Bootstrap contract** (handled by ``WebGuardMiddleware`` itself; Task 5/7 must NOT
  add a route for it): ``GET <bootstrap_path>?k=<token>`` (default ``/?k=<token>``).
  The token is compared in constant time and is **single use**: on success the
  middleware answers ``303 -> /`` with a ``Set-Cookie`` (``HttpOnly``,
  ``SameSite=Strict``, ``Path=/``, ``Max-Age``) and the bootstrap is then burned (any
  later ``?k=`` gets 401). A wrong token gets 401 and does not burn it.
  The cookie value is the Web token itself; ``verify_cookie`` checks it.
* Every other request needs that cookie (401). ``Authorization: Bearer <mcp-token>``
  is never looked at, so the MCP credential grants no Web access whatsoever.
* ``Host`` must be ``127.0.0.1:<port>`` / ``localhost:<port>`` on every request
  (DNS-rebinding defence; 403). Unsafe methods (anything but GET/HEAD/OPTIONS) also
  need a same-origin ``Origin`` header (403, checked before the cookie). An ``Origin``
  that is present on a safe request must also be valid. Page navigations send no
  Origin and are exempt.
* Cookie is not ``Secure``: the server speaks plain http on loopback.
* WebSocket scopes are refused (the Web client uses SSE + POST only).
Order of checks: Host/Origin (403) -> bootstrap -> cookie (401).
"""
from __future__ import annotations

import hmac
import os
import secrets
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

COOKIE_NAME = "carbon_web"
BOOTSTRAP_PATH = "/"
BOOTSTRAP_PARAM = "k"
COOKIE_MAX_AGE = 8 * 3600
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_LOOPBACK_NAMES = ("127.0.0.1", "localhost")


def new_web_token() -> str:
    return secrets.token_urlsafe(32)


def write_web_token(token: str) -> Path:
    """Write the token to a fresh, randomly named 0600 file (mkstemp: O_EXCL)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    fd, name = tempfile.mkstemp(prefix="carbon-web-token-", dir=base)
    with os.fdopen(fd, "w") as fh:
        fh.write(token)
    return Path(name)


def verify_cookie(cookie_value: str | None, token: str) -> bool:
    """Constant-time check of the session cookie against the stored Web token."""
    if not cookie_value or not token:
        return False
    return hmac.compare_digest(cookie_value.encode(), token.encode())


def _get(headers: Mapping[str, Any], name: str) -> str | None:
    value = headers.get(name)
    if value is None:  # plain dicts may be differently cased
        for k, v in headers.items():
            if str(k).lower() == name:
                value = v
                break
    return value


def _allowed_hosts(host: str, port: int) -> set[str]:
    return {f"{n}:{port}" for n in {host, *_LOOPBACK_NAMES}}


def valid_host(headers: Mapping[str, Any], host: str, port: int) -> bool:
    h = _get(headers, "host")
    return bool(h) and h.lower() in _allowed_hosts(host, port)


def valid_origin(headers: Mapping[str, Any], host: str, port: int) -> bool:
    """Same-origin check: ``Origin`` present and loopback:port, and ``Host`` matches."""
    if not valid_host(headers, host, port):
        return False
    origin = _get(headers, "origin")
    if not origin:
        return False
    return origin.lower() in {f"http://{a}" for a in _allowed_hosts(host, port)}


class WebGuardMiddleware:
    """Pure ASGI guard for the Web routes (see module docstring for the contract)."""

    def __init__(
        self, app: Any, token: str, port: int, *, host: str = "127.0.0.1",
        cookie_name: str = COOKIE_NAME, bootstrap_path: str = BOOTSTRAP_PATH,
    ) -> None:
        self.app = app
        self._token = token
        self._port = port
        self._host = host
        self._cookie_name = cookie_name
        self._bootstrap_path = bootstrap_path
        self._consumed = False

    @staticmethod
    async def _respond(send, status: int, body: bytes, extra=()) -> None:
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"), *extra]})
        await send({"type": "http.response.body", "body": body})

    def _cookie_of(self, headers: Mapping[str, str]) -> str | None:
        for part in headers.get("cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == self._cookie_name:
                return value
        return None

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        method = scope["method"].upper()

        if not valid_host(headers, self._host, self._port):
            return await self._respond(send, 403, b'{"error":"bad host"}')
        if "origin" in headers or method not in _SAFE_METHODS:
            if not valid_origin(headers, self._host, self._port):
                return await self._respond(send, 403, b'{"error":"bad origin"}')

        if method == "GET" and scope["path"] == self._bootstrap_path:
            supplied = parse_qs(scope.get("query_string", b"").decode("latin-1")).get(
                BOOTSTRAP_PARAM)
            if supplied:
                ok = verify_cookie(supplied[0], self._token) and not self._consumed
                if not ok:
                    return await self._respond(send, 401, b'{"error":"unauthorized"}')
                self._consumed = True
                cookie = (f"{self._cookie_name}={self._token}; HttpOnly; SameSite=Strict; "
                          f"Path=/; Max-Age={COOKIE_MAX_AGE}")
                return await self._respond(send, 303, b"", (
                    (b"location", b"/"), (b"set-cookie", cookie.encode()),
                    (b"referrer-policy", b"no-referrer")))

        if not verify_cookie(self._cookie_of(headers), self._token):
            return await self._respond(send, 401, b'{"error":"unauthorized"}')
        await self.app(scope, receive, send)
