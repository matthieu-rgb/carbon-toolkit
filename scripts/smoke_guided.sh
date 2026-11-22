#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Smoke test of the guided methodology ENGINE (not the TUI) against the simulated
# ECU on a virtual channel: walk carbon_v1 steps 1->6 (destructive steps approved
# from a worker thread via the ApprovalQueue), reach the final step, then check
# that Session.resume restores the same position.
# Exit 0 and prints "smoke GUIDED OK" on success, non-zero otherwise.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="${CARBON_PYTHON:-}"
if [ -z "$PY" ]; then
    if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY=python3; fi
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

CARBON_SMOKE_WORK="$WORK" CARBON_SMOKE_TREE="$ROOT/carbon/methodology/trees/carbon_v1.yaml" \
"$PY" -I - <<'PY' || { echo "SMOKE FAIL: GUIDED" >&2; exit 1; }
import os, threading
from pathlib import Path
from carbon.can.bus import open_bus, send_frame
from carbon.core.execute import Decision, Origin
from carbon.core.session import Session
from carbon.emu.ecu import SimulatedEcu
from carbon.mcp.approval import ApprovalQueue

CH = "carbon-smoke-guided"
WORK = Path(os.environ["CARBON_SMOKE_WORK"])
TREE = os.environ["CARBON_SMOKE_TREE"]
state_path, journal = WORK / "state.json", WORK / "journal.jsonl"
capture = WORK / "capture.log"
capture.write_text("(0.000000) %s 123#DEADBEEF\n" % CH, encoding="utf-8")

def check(cond, msg):
    if not cond:
        raise SystemExit(f"SMOKE FAIL: {msg}")

queue = ApprovalQueue(timeout=30)
stop = threading.Event()
approved = []

def approver():
    while not stop.is_set():
        for p in queue.pending():
            approved.append(p.tool)
            print(f"[approver] approving {p.tool}")
            queue.resolve(p.id, Decision.APPROVED)
        stop.wait(0.05)

def traffic(stop_evt):
    # Second bus on the same virtual channel, emitting until the sniff ends.
    bus = open_bus(CH, "virtual")
    try:
        while not stop_evt.is_set():
            send_frame(bus, 0x321, b"\x01\x02\x03")
            stop_evt.wait(0.02)
    finally:
        bus.shutdown()

def step(sess, tool, expect_next, **params):
    cur = sess.engine.current().id
    r = sess.run_tool(tool, origin=Origin.TUI, **params)
    print(f"[{cur}] {tool}: ok={r.ok} {r.summary}")
    check(r.ok, f"{tool} failed: {r.summary}")
    check(sess.engine.current().id == expect_next,
          f"after {tool}: at {sess.engine.current().id}, expected {expect_next}")

with SimulatedEcu(CH, interface="virtual") as ecu:
    check(ecu.ready.is_set(), "ECU not ready")
    sess = Session(channel=CH, interface="virtual", journal_path=journal,
                   approver=queue, state_path=state_path)
    sess.load_methodology(TREE)
    check(sess.mode == "guided", "not in guided mode")
    check(sess.engine.current().id == "acces", "wrong start step")
    sess.step_ack()  # 1. acces
    check(sess.engine.current().id == "recon", "ack did not advance to recon")

    # Out-of-path tool is refused in guided mode.
    r = sess.run_tool("can_inject", origin=Origin.TUI, arb_id="123", data="00")
    check(not r.ok and "hors parcours" in r.summary, "guided guard did not block")

    tstop = threading.Event()
    tthread = threading.Thread(target=traffic, args=(tstop,), daemon=True)
    tthread.start()
    try:
        step(sess, "can_sniff", "uds_scan", count=3, timeout=5.0)
    finally:
        tstop.set()
        tthread.join(timeout=5)

    step(sess, "uds_scan", "uds_session")
    step(sess, "uds_session", "lire_dtc", session="extended")
    step(sess, "uds_read_dtc", "seed_key")
    step(sess, "uds_security_access", "effacer_dtc")

    threading.Thread(target=approver, daemon=True).start()
    step(sess, "uds_clear_dtc", "rejeu")
    step(sess, "can_replay", "injection", path=str(capture))
    r = sess.run_tool("can_inject", origin=Origin.TUI, arb_id=0x123, data="DEADBEEF")
    print(f"[injection] can_inject: ok={r.ok} {r.summary}")
    check(r.ok, f"can_inject failed: {r.summary}")
    stop.set()

    check(set(approved) >= {"uds_clear_dtc", "can_replay", "can_inject"},
          f"destructive steps not all approved: {approved}")
    final = sess.engine.current().id
    check(final == "injection", f"final step not reached: {final}")
    check(sess.engine.satisfied, "final step not satisfied")

    resumed = Session.resume(state_path, channel=CH, interface="virtual",
                             journal_path=journal)
    check(resumed.engine.current().id == final,
          f"resume at {resumed.engine.current().id}, expected {final}")
    check(resumed.engine.satisfied == sess.engine.satisfied, "satisfied not restored")
    check(resumed.mode == "guided", "mode not restored")

print("smoke GUIDED OK")
PY
