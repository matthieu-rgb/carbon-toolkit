# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from carbon.core.session import Session
from carbon.mcp.approval import ApprovalQueue
from carbon.web.app import build_web_app
from carbon.web.events import Broker
from carbon.web.security import new_web_token

PORT = 8782
STATIC = Path(__file__).resolve().parents[2] / "carbon" / "web" / "static"


@pytest.fixture
def client(tmp_path):
    token = new_web_token()
    session = Session(channel="carbon-web-static", interface="virtual",
                      journal_path=tmp_path / "j.jsonl")
    app = build_web_app(session, Broker(), ApprovalQueue(timeout=5), token, PORT)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    c.cookies.set("carbon_web", token)
    return c


def test_index_has_mount_points(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    for needle in ('id="cy"', 'id="journal"', 'id="tools"', 'id="modals"',
                   "/static/app.js", "/static/style.css"):
        assert needle in r.text


def test_vendored_cytoscape_served_and_licensed(client):
    r = client.get("/static/vendor/cytoscape.min.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "cytoscape" in r.text[:100000].lower()
    lic = (STATIC / "vendor" / "cytoscape.LICENSE").read_text()
    assert "Permission is hereby granted" in lic


def test_app_and_css_served(client):
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_static_requires_cookie(client):
    client.cookies.clear()
    assert client.get("/static/app.js").status_code in (401, 403)


def test_no_external_refs_air_gap():
    html = (STATIC / "index.html").read_text()
    assert not re.findall(r'(?:src|href)\s*=\s*["\']?\s*(?:https?:)?//', html, re.I)
    css = (STATIC / "style.css").read_text()
    assert not re.search(r"(?:@import|url\()\s*[\"']?\s*(?:https?:)?//", css, re.I)


def test_app_js_uses_api():
    js = (STATIC / "app.js").read_text()
    assert "/api/events" in js and "/api/tool/" in js and "/api/approvals/" in js
    assert "assume_yes" not in js


def test_approval_hotkeys_scoped_to_modal_and_escape_inert():
    js = (STATIC / "app.js").read_text()
    # hotkeys live on the modal element, guarded by focus containment
    assert 'm.addEventListener("keydown"' in js and "m.contains(document.activeElement)" in js
    # no document-level handler may decide an approval, and Escape never denies
    assert "_decide" not in js and "Escape\") {\n      top" not in js
    assert 'e.key === "Escape") { top' not in js
    # modal is dismissed only on success or 409
    assert "r.ok || r.status === 409" in js
