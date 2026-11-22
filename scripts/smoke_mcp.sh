#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Smoke test of the MCP server (in-memory client) against the simulated ECU on a
# virtual channel: list tools, uds_scan, session_state, journal resource, and a
# destructive tool that goes pending-approval then executes once approved.
# Exit 0 and prints "smoke MCP OK" on success, non-zero otherwise.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="${CARBON_PYTHON:-}"
if [ -z "$PY" ]; then
    if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY=python3; fi
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

CARBON_SMOKE_JOURNAL="$WORK/journal.jsonl" "$PY" - <<'PY' || { echo "SMOKE FAIL: MCP" >&2; exit 1; }
import asyncio, json, os, threading
from mcp import Client
from carbon.core.session import Session
from carbon.emu.ecu import SimulatedEcu
from carbon.mcp.approval import ApprovalQueue
from carbon.mcp.server import build_mcp_server

CH = "carbon-smoke-mcp"
queue = ApprovalQueue(timeout=30)
stop = threading.Event()
seen = []

def approver():
    while not stop.is_set():
        for p in queue.pending():
            seen.append(p.id)
            print(f"[approver] approving {p.tool} ({p.id})")
            from carbon.core.execute import Decision
            queue.resolve(p.id, Decision.APPROVED)
        stop.wait(0.05)

def check(cond, msg):
    if not cond:
        raise SystemExit(f"SMOKE FAIL: {msg}")

async def main():
    session = Session(channel=CH, interface="virtual",
                      journal_path=__import__("pathlib").Path(os.environ["CARBON_SMOKE_JOURNAL"]),
                      approver=queue)
    async with Client(build_mcp_server(session)) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        check({"uds_scan", "uds_clear_dtc", "session_state"} <= names, f"tools: {names}")
        scan = await c.call_tool("uds_scan", {})
        check(not scan.is_error, "uds_scan errored")
        print("[scan]", scan.structured_content)
        st = await c.call_tool("session_state", {})
        check(not st.is_error, "session_state errored")
        for tool in ("uds_session", "uds_security_access"):
            r = await c.call_tool(tool, {})
            check(r.structured_content["ok"], f"{tool} failed")
        threading.Thread(target=approver, daemon=True).start()
        clr = await c.call_tool("uds_clear_dtc", {})
        print("[clear]", clr.structured_content)
        check(seen, "destructive call never reached pending-approval")
        check(clr.structured_content["ok"], "destructive call failed after approval")
        res = await c.read_resource("carbon://journal")
        text = "".join(getattr(x, "text", "") for x in res.contents)
        check("uds_clear_dtc" in text and "uds_scan" in text, "journal lacks entries")

with SimulatedEcu(CH, interface="virtual") as ecu:
    check(ecu.ready.is_set(), "ECU not ready")
    asyncio.run(main())
stop.set()
print("smoke MCP OK")
PY
