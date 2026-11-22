#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Non-interactive smoke of the Web client (no browser, no curl): start
# `carbon web` in the background on a virtual channel, follow the one-time
# bootstrap URL to obtain the `carbon_web` cookie, then check that /api/state
# serves the session state ("surface" + "tools") with the cookie and is refused
# without it, that the bootstrap link is one-time, and that /mcp is NOT
# reachable with the web cookie (separate Bearer token domain).
# Scope: proves live session state, cookie auth and the state shape. The
# simulated ECU is not started: real tool-over-CAN runs are covered by the
# in-process test suite (the virtual bus is not shared across processes).
# Exit 0 and prints "WEB OK" on success, non-zero otherwise.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="${CARBON_PYTHON:-}"
if [ -z "$PY" ]; then
    if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY=python3; fi
fi

WORK="$(mktemp -d)"
WEB_PID=""
cleanup() {
    if [ -n "$WEB_PID" ] && kill -0 "$WEB_PID" 2>/dev/null; then
        kill "$WEB_PID" 2>/dev/null || true
        for _ in $(seq 1 30); do
            kill -0 "$WEB_PID" 2>/dev/null || break
            sleep 0.1
        done
        kill -9 "$WEB_PID" 2>/dev/null || true
    fi
    wait 2>/dev/null || true
    rm -rf "$WORK"
}
trap cleanup EXIT

fail() { echo "SMOKE FAIL: WEB: $*" >&2; exit 1; }

PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"

"$PY" -m carbon.cli --interface virtual --channel carbon-smoke-web \
    --journal "$WORK/journal.jsonl" web --port "$PORT" >"$WORK/web.log" 2>&1 &
WEB_PID=$!

# Wait for the bootstrap URL to be announced.
URL=""
for _ in $(seq 1 150); do
    URL="$(grep -o "http://127.0.0.1:$PORT/?k=[A-Za-z0-9_-]*" "$WORK/web.log" 2>/dev/null | head -n1 || true)"
    [ -n "$URL" ] && break
    kill -0 "$WEB_PID" 2>/dev/null || { cat "$WORK/web.log" >&2; fail "carbon web exited early"; }
    sleep 0.1
done
[ -n "$URL" ] || { cat "$WORK/web.log" >&2; fail "no bootstrap URL printed (timeout)"; }

PORT="$PORT" URL="$URL" "$PY" -I - <<'PY' || fail "HTTP checks failed (see above)"
import http.client, json, os, sys, time
from urllib.parse import urlsplit

PORT = int(os.environ["PORT"])
URL = os.environ["URL"]
ORIGIN = f"http://127.0.0.1:{PORT}"

def req(path, cookie=None, method="GET"):
    h = {"Origin": ORIGIN}
    if cookie:
        h["Cookie"] = cookie
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    try:
        c.request(method, path, headers=h)
        r = c.getresponse()
        return r.status, r.getheaders(), r.read()
    finally:
        c.close()

def check(cond, msg):
    if not cond:
        print(f"check failed: {msg}", file=sys.stderr)
        sys.exit(1)

# Readiness: server must answer (401 without cookie), else fail explicitly.
for _ in range(100):
    try:
        status, _, _ = req("/api/state")
        break
    except OSError:
        time.sleep(0.1)
else:
    check(False, "server never came up")
check(status == 401, f"/api/state without cookie: {status}, expected 401")

boot = urlsplit(URL)
path = boot.path + "?" + boot.query
status, hdrs, _ = req(path)
check(status == 303, f"bootstrap returned {status}, expected 303")
cookies = [v for k, v in hdrs if k.lower() == "set-cookie" and v.startswith("carbon_web=")]
check(cookies, "no carbon_web cookie set")
cookie = cookies[0].split(";", 1)[0]

status, _, body = req("/api/state", cookie)
check(status == 200, f"/api/state with cookie: {status}")
d = json.loads(body)
check("surface" in d and "tools" in d and d["tools"], f"bad state keys: {sorted(d)}")
print("state keys:", sorted(d), "| tools:", len(d["tools"]))

# One-time link: reuse must not mint a session.
status, hdrs, _ = req(path)
check(status in (401, 403), f"bootstrap reuse returned {status}, expected 401/403")
check(not any(k.lower() == "set-cookie" for k, _ in hdrs), "reuse set a cookie")

# The web cookie must not satisfy the MCP Bearer guard.
status, _, _ = req("/mcp", cookie)
check(status == 401, f"/mcp with web cookie: {status}, expected 401")
PY

echo "WEB OK"
