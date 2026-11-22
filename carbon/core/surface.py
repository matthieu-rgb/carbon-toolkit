# SPDX-License-Identifier: GPL-3.0-or-later
"""Attack-surface projection: a pure, monotonic fold over tool-run history.

Works on ``ToolResult.to_dict()`` dicts only; knows nothing of tools or
methodology. Nodes accumulate by id and are never removed.
"""
from __future__ import annotations

from typing import Any

UDS_ECU = "0x7e8"  # UDS responder arbitration-id convention

_TOOL_NODE = {  # guided override: tool -> node kind
    "can_sniff": "bus", "can_inject": "bus",
    "uds_scan": "ecu", "uds_session": "ecu", "uds_read_dtc": "ecu",
    "uds_security_access": "level",
}


def build_surface(history: list[dict], *, channel: str,
                  current_tool: str | None = None) -> dict[str, Any]:
    bus = f"bus:{channel}"
    nodes: dict[str, dict[str, Any]] = {
        bus: {"id": bus, "type": "bus", "label": channel}}
    edges: dict[tuple[str, str], dict[str, str]] = {}
    session: dict[str, Any] = {"active": None, "unlocked": False}
    current: str | None = None

    def add(nid: str, typ: str, label: str, parent: str | None = None,
            state: str | None = None) -> str:
        n = nodes.get(nid)
        if n is None:
            n = nodes[nid] = {"id": nid, "type": typ, "label": label}
            if parent is not None:
                n["parent"] = parent
                edges[(parent, nid)] = {"source": parent, "target": nid}
        if state is not None:
            n["state"] = state
        return nid

    ecu = f"ecu:{UDS_ECU}"

    def uds_ecu() -> str:
        return add(ecu, "ecu", UDS_ECU, bus)

    for r in history:
        if not r.get("ok"):
            continue
        tool = r.get("tool")
        data = r.get("data") or {}
        if tool == "can_sniff":
            for f in (data.get("frames") or []):
                arb = f.get("arbitration_id")
                if isinstance(arb, int):
                    add(f"ecu:0x{arb:x}", "ecu", f"0x{arb:x}", bus)
            current = bus
        elif tool == "can_inject":
            arb = data.get("arbitration_id")
            current = (add(f"ecu:0x{arb:x}", "ecu", f"0x{arb:x}", bus)
                       if isinstance(arb, int) else bus)
        elif tool == "uds_scan":
            uds_ecu()
            for svc in (data.get("supported") or []):
                add(f"svc:{UDS_ECU}:{svc}", "service", str(svc), ecu)
            current = ecu
        elif tool == "uds_session":
            uds_ecu()
            if data.get("session") and not data.get("nrc"):
                session["active"] = data["session"]
                nodes[ecu]["state"] = data["session"]
            current = ecu
        elif tool == "uds_security_access":
            uds_ecu()
            if data.get("unlocked") is True:
                session["unlocked"] = True
                current = add(f"level:{UDS_ECU}", "level", "security", ecu,
                              state="unlocked")
            else:
                current = ecu
        elif tool == "uds_read_dtc":
            uds_ecu()
            for d in (data.get("dtcs") or []):
                code = d.get("code") if isinstance(d, dict) else str(d)
                add(f"dtc:{UDS_ECU}:{code}", "dtc", str(code), ecu,
                    state=d.get("status") if isinstance(d, dict) else None)
            current = ecu

    kind = _TOOL_NODE.get(current_tool or "")
    override = {"bus": bus, "ecu": ecu, "level": f"level:{UDS_ECU}"}.get(kind or "")
    if override in nodes:
        current = override

    return {"nodes": list(nodes.values()), "edges": list(edges.values()),
            "current": current, "session": session}
