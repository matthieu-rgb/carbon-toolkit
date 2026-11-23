# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation helpers for the TUI.

Phase rail, plain-French interpretation of a tool result, and the services
panel view. No Textual, no engine mutation — testable in isolation, so the app
stays a thin façade.
"""
from __future__ import annotations

import re
from typing import Any

# The six phases of a complete CAN/UDS assessment (DESIGN §6). The methodology
# step titles are numbered ("1. Accès", "3a. ...", "4b. ..."), so the leading
# digit maps any step to its phase.
PHASES: list[tuple[int, str]] = [
    (1, "Accès"), (2, "Recon"), (3, "UDS"),
    (4, "DTC"), (5, "Seed-key"), (6, "Inject"),
]


def phase_of(title: str) -> int | None:
    """The phase number a step title belongs to, or None."""
    m = re.match(r"\s*(\d+)", title or "")
    return int(m.group(1)) if m else None


def progress_rail(current_title: str) -> str:
    """Rich markup for the phase rail: earlier phases done, current active."""
    cur = phase_of(current_title) or 0
    cells = []
    for num, label in PHASES:
        if num < cur:
            cells.append(f"[green]●[/] [dim]{label}[/]")
        elif num == cur:
            cells.append(f"[b yellow]◆ {label}[/]")
        else:
            cells.append(f"[dim]○ {label}[/]")
    return "   ".join(cells)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def interpret(result: dict[str, Any]) -> str:
    """One plain-French line explaining what a tool result means.

    ``result`` is a ToolResult.to_dict(). Falls back to the raw summary for any
    tool or shape not handled here, so it never raises.
    """
    tool = result.get("tool", "")
    ok = bool(result.get("ok"))
    data = result.get("data") or {}
    nrc = data.get("nrc", "?")

    if tool == "uds_scan":
        sup = data.get("supported") or []
        msg = f"{len(sup)} service(s) répondent"
        if any(str(s).lower() == "0x27" for s in sup):
            msg += " · 0x27 présent → seed-key possible"
        return msg
    if tool == "uds_session":
        return (f"session {data.get('session', '?')} ouverte" if ok
                else f"session refusée (NRC {nrc})")
    if tool == "uds_security_access":
        return (f"déverrouillé · niveau {data.get('level', '?')}" if ok
                else f"déverrouillage refusé (NRC {nrc})")
    if tool == "uds_read_dtc":
        return (f"{len(data.get('dtcs') or [])} DTC" if ok
                else f"lecture DTC refusée (NRC {nrc})")
    if tool == "uds_clear_dtc":
        return "DTC effacés" if ok else f"effacement refusé (NRC {nrc})"
    if tool == "uds_read_did":
        return (f"DID 0x{_as_int(data.get('did')):X} = {data.get('value', '?')}" if ok
                else f"DID verrouillé (NRC {nrc})")
    if tool == "can_sniff":
        frames = data.get("frames")
        n = len(frames) if isinstance(frames, list) else _as_int(frames)
        return f"{n} trame(s) capturée(s)"
    if tool in ("can_replay", "can_dump"):
        return f"{data.get('frames', '?')} trame(s)"
    if tool == "can_inject":
        return f"trame 0x{_as_int(data.get('arbitration_id')):X} injectée"
    return result.get("summary", "")


# Known UDS service codes → short French names for the services panel.
_SERVICE_NAMES = {
    "0x10": "session", "0x11": "reset", "0x14": "effacer DTC",
    "0x19": "lire DTC", "0x22": "lire DID", "0x27": "sécurité",
    "0x2e": "écrire DID", "0x31": "routine", "0x3e": "présence",
}


_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: Any, width: int = 12) -> str:
    """A block sparkline of the last ``width`` values, scaled to the window's max."""
    vals = [float(v) for v in list(values)[-width:]]
    vals = [0.0] * (width - len(vals)) + vals
    hi = max(vals)
    if hi <= 0:
        return _BLOCKS[0] * width
    out = []
    for v in vals:
        idx = 0 if v <= 0 else min(len(_BLOCKS) - 1, 1 + int(v / hi * (len(_BLOCKS) - 2)))
        out.append(_BLOCKS[idx])
    return "".join(out)


def device_box(*, unlocked: bool, session: str | None) -> str:
    """A compact pixel-style ECU card, colored by lock state (rich markup)."""
    colour = "green" if unlocked else "red"
    lock = "unlocked" if unlocked else "locked "
    sess = (session or "—")[:9].ljust(9)
    return (
        f"[{colour}]┌───────────┐[/]\n"
        f"[{colour}]│[/] [b]ECU 0x7E8[/] [{colour}]│[/]\n"
        f"[{colour}]│[/] 7E0→7E8  [{colour}]│[/]\n"
        f"[{colour}]│[/] {sess}[{colour}]│[/]\n"
        f"[{colour}]└──── {lock}─┘[/]"
    )


def banner_for(result: dict[str, Any]) -> tuple[str, str] | None:
    """A milestone banner (text, css-class) for a result, or None.

    Milestones are the moments worth shouting about: a security unlock, DTCs
    cleared, a protected DID read. They light up the top banner (wifite3's
    "WPS PSK recovered" moment) and stay until the next milestone.
    """
    tool = result.get("tool", "")
    ok = bool(result.get("ok"))
    data = result.get("data") or {}
    if not ok:
        return None
    if tool == "uds_security_access":
        return (f"✓  SÉCURITÉ DÉVERROUILLÉE · niveau {data.get('level', '?')}", "banner-ok")
    if tool == "uds_clear_dtc":
        return ("✓  DTC EFFACÉS", "banner-ok")
    if tool == "uds_read_did":
        return (f"✓  DID 0x{_as_int(data.get('did')):X} LU · {data.get('value', '?')}", "banner-ok")
    return None


def journal_entries(result: dict[str, Any]) -> list[str]:
    """One or more plain log lines for a result.

    Seed-key is expanded into its challenge/response sequence (requestSeed →
    sendKey → unlocked), which reads like wifite3's M1→M8 handshake; every other
    tool is a single interpreted line.
    """
    tool = result.get("tool", "")
    ok = bool(result.get("ok"))
    data = result.get("data") or {}
    if tool == "uds_security_access":
        seed = data.get("seed", "?")
        lines = [f"seed-key : requestSeed → seed {seed}", "  clé calculée → sendKey"]
        lines.append(f"✓ niveau {data.get('level', '?')} déverrouillé" if ok
                     else f"✗ refusé (NRC {data.get('nrc', '?')})")
        return lines
    return [interpret(result)]


def services_from_surface(surface: dict[str, Any]) -> list[dict[str, str]]:
    """Service and security-level entries for the services panel, from the surface."""
    nodes = (surface or {}).get("nodes") or []
    out: list[dict[str, str]] = []
    for n in nodes:
        typ = n.get("type")
        if typ == "service":
            code = str(n.get("label", "?"))
            out.append({"label": code, "name": _SERVICE_NAMES.get(code.lower(), "")})
        elif typ == "level":
            state = "déverrouillé" if n.get("state") == "unlocked" else "verrouillé"
            out.append({"label": "sécurité", "name": state})
    return out
