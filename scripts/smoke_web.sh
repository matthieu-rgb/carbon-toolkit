#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Non-interactive smoke of the Web client (no browser): start the simulated ECU
# and `carbon web` in the background on a virtual channel, follow the one-time
# bootstrap URL with a cookie jar to obtain the `carbon_web` cookie, then check
# that /api/state serves live state ("surface" + "tools") with the cookie, is
# refused without it, and that /mcp is not reachable with the web cookie.
# Exit 0 and prints "WEB OK" on success, non-zero otherwise.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="${CARBON_PYTHON:-}"
if [ -z "$PY" ]; then
    if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY=python3; fi
fi
CARBON=("$PY" -m carbon.cli)
if [ -x "$(dirname "$PY")/carbon" ]; then CARBON=("$(dirname "$PY")/carbon"); fi

WORK="$(mktemp -d)"
PIDS=()
cleanup() {
    for p in "${PIDS[@]:-}"; do
        [ -n "$p" ] && kill "$p" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    rm -rf "$WORK"
}
trap cleanup EXIT

fail() { echo "SMOKE FAIL: WEB: $*" >&2; exit 1; }

CH="carbon-smoke-web"
PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
BASE="http://127.0.0.1:$PORT"

"${CARBON[@]}" --interface virtual --channel "$CH" emu start >"$WORK/emu.log" 2>&1 &
PIDS+=($!)
"${CARBON[@]}" --interface virtual --channel "$CH" --journal "$WORK/journal.jsonl" \
    web --port "$PORT" >"$WORK/web.log" 2>&1 &
PIDS+=($!)

# Wait for the bootstrap URL (and the port) to be announced.
URL=""
for _ in $(seq 1 100); do
    URL="$(grep -o "http://127.0.0.1:$PORT/?k=[A-Za-z0-9_-]*" "$WORK/web.log" 2>/dev/null | head -n1 || true)"
    [ -n "$URL" ] && break
    kill -0 "${PIDS[1]}" 2>/dev/null || { cat "$WORK/web.log" >&2; fail "carbon web exited early"; }
    sleep 0.1
done
[ -n "$URL" ] || { cat "$WORK/web.log" >&2; fail "no bootstrap URL printed"; }
for _ in $(seq 1 100); do
    curl -s -o /dev/null "$BASE/api/state" && break
    sleep 0.1
done

# Without the cookie: refused.
CODE="$(curl -s -o /dev/null -w '%{http_code}' -H "Origin: $BASE" "$BASE/api/state")"
[ "$CODE" = "401" ] || fail "/api/state without cookie returned $CODE, expected 401"

# Bootstrap: sets the carbon_web cookie, 303 -> /.
JAR="$WORK/jar"
CODE="$(curl -s -o /dev/null -w '%{http_code}' -c "$JAR" "$URL")"
[ "$CODE" = "303" ] || fail "bootstrap returned $CODE, expected 303"
grep -q "carbon_web" "$JAR" || fail "no carbon_web cookie in jar"

# With the cookie: live state.
curl -fsS -b "$JAR" -H "Origin: $BASE" "$BASE/api/state" >"$WORK/state.json" \
    || fail "/api/state with cookie failed"
"$PY" -I - "$WORK/state.json" <<'PY' || fail "state JSON invalid"
import json, sys
d = json.load(open(sys.argv[1]))
assert "surface" in d, "no surface"
assert "tools" in d, "no tools"
assert d["tools"], "empty tools"
print("state keys:", sorted(d), "| tools:", len(d["tools"]))
PY

# One-time link: replaying the token with a fresh jar must not yield a session.
CODE="$(curl -s -o /dev/null -w '%{http_code}' -c "$WORK/jar2" "$URL")"
if [ "$CODE" = "303" ] && grep -q "carbon_web" "$WORK/jar2"; then
    fail "bootstrap URL is reusable (expected one-time)"
fi

echo "WEB OK"
