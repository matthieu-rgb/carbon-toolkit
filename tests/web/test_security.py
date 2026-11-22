# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
import stat

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from carbon.mcp.transport import verify_token
from carbon.web.security import (
    WebGuardMiddleware, new_web_token, valid_origin, verify_cookie, write_web_token,
)

PORT = 8780
BASE = f"http://127.0.0.1:{PORT}"
MCP_TOKEN = "mcp-secret-token"


def _app(token: str):
    async def ok(request):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[
        Route("/", ok, methods=["GET", "POST"]),
        Route("/api/state", ok, methods=["GET", "POST"]),
    ])
    return WebGuardMiddleware(inner, token, PORT)


def _client(token: str) -> TestClient:
    return TestClient(_app(token), base_url=BASE, follow_redirects=False)


def test_new_token_is_random_and_long():
    assert new_web_token() != new_web_token()
    assert len(new_web_token()) >= 32


def test_write_web_token_0600_distinct_file():
    p = write_web_token("abc")
    try:
        assert p.read_text() == "abc"
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
        assert "web" in p.name
    finally:
        p.unlink()


def test_verify_cookie_constant_time_match():
    assert verify_cookie("tok", "tok") is True


def test_verify_cookie_mismatch():
    assert verify_cookie("bad", "tok") is False
    assert verify_cookie(None, "tok") is False
    assert verify_cookie("", "tok") is False


def test_valid_origin_accepts_localhost():
    for o in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
        assert valid_origin({"origin": o, "host": f"127.0.0.1:{PORT}"}, "127.0.0.1", PORT)
    assert valid_origin({"origin": BASE, "host": f"localhost:{PORT}"}, "127.0.0.1", PORT)


def test_valid_origin_rejects_foreign():
    h = {"origin": "http://evil.example", "host": f"127.0.0.1:{PORT}"}
    assert not valid_origin(h, "127.0.0.1", PORT)
    assert not valid_origin({"origin": "null", "host": f"127.0.0.1:{PORT}"}, "127.0.0.1", PORT)
    assert not valid_origin({"origin": f"http://127.0.0.1:{PORT + 1}", "host": f"127.0.0.1:{PORT}"},
                            "127.0.0.1", PORT)
    assert not valid_origin({"host": f"127.0.0.1:{PORT}"}, "127.0.0.1", PORT)  # Origin required


def test_valid_origin_rejects_mismatched_host():
    assert not valid_origin({"origin": BASE, "host": "evil.example"}, "127.0.0.1", PORT)
    assert not valid_origin({"origin": BASE, "host": "evil.example:8780"}, "127.0.0.1", PORT)
    assert not valid_origin({"origin": BASE}, "127.0.0.1", PORT)


def test_middleware_blocks_without_cookie():
    assert _client("tok").get("/api/state").status_code == 401


def test_mcp_bearer_does_not_satisfy_web():
    # KEY GUARANTEE: the MCP Bearer token alone never opens a Web route.
    assert verify_token(f"Bearer {MCP_TOKEN}", MCP_TOKEN)  # it is a valid MCP credential...
    c = _client(new_web_token())
    hdr = {"Authorization": f"Bearer {MCP_TOKEN}"}
    assert c.get("/api/state", headers=hdr).status_code == 401
    assert c.post("/api/state", headers={**hdr, "Origin": BASE}).status_code == 401
    # ...and even presented as the Web token via bootstrap or cookie it is refused
    assert c.get(f"/?k={MCP_TOKEN}").status_code == 401
    c.cookies.set("carbon_web", MCP_TOKEN)
    assert c.get("/api/state", headers=hdr).status_code == 401


def test_bootstrap_sets_hardened_cookie_and_redirects():
    c = _client("tok")
    r = c.get("/?k=tok")
    assert r.status_code == 303 and r.headers["location"] == "/"
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "path=/" in sc and "max-age=" in sc
    assert r.headers["referrer-policy"] == "no-referrer"
    assert c.get("/api/state").text == "ok"  # cookie now authenticates


def test_bootstrap_is_one_time():
    c = _client("tok")
    assert c.get("/?k=tok").status_code == 303
    assert _client_retry(c).status_code == 401


def _client_retry(c):
    c.cookies.clear()
    return c.get("/?k=tok")


def test_bootstrap_wrong_token_rejected_and_not_consumed():
    c = _client("tok")
    assert c.get("/?k=nope").status_code == 401
    assert c.get("/?k=tok").status_code == 303


def test_middleware_blocks_foreign_origin_post():
    c = _client("tok")
    c.get("/?k=tok")
    r = c.post("/api/state", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert c.post("/api/state").status_code == 403  # no Origin on POST
    assert c.post("/api/state", headers={"Origin": BASE}).status_code == 200


def test_foreign_origin_blocked_even_without_cookie():
    assert _client("tok").post("/api/state", headers={"Origin": "http://evil.example"}).status_code == 403


def test_dns_rebinding_host_rejected_on_get():
    c = _client("tok")
    c.get("/?k=tok")
    assert c.get("/api/state", headers={"Host": "evil.example:8780"}).status_code == 403


def test_get_page_is_origin_exempt():
    c = _client("tok")
    c.get("/?k=tok")
    assert c.get("/api/state").status_code == 200  # navigation: no Origin header
