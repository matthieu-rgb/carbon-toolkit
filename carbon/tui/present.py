# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation helpers for the TUI.

Phase rail, plain-French interpretation of a tool result, and the services
panel view. No Textual, no engine mutation - testable in isolation, so the app
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
            msg += " - 0x27 présent -> seed-key possible"
        return msg
    if tool == "uds_session":
        return (f"session {data.get('session', '?')} ouverte" if ok
                else f"session refusée (NRC {nrc})")
    if tool == "uds_security_access":
        return (f"déverrouillé - niveau {data.get('level', '?')}" if ok
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


# Known UDS service codes -> short French names for the services panel.
_SERVICE_NAMES = {
    "0x10": "session", "0x11": "reset", "0x14": "effacer DTC",
    "0x19": "lire DTC", "0x22": "lire DID", "0x27": "sécurité",
    "0x2e": "écrire DID", "0x31": "routine", "0x3e": "présence",
}


def hbar(value: float, maxval: float, width: int = 16) -> str:
    """A horizontal fill bar, e.g. ``██████░░░░``, value scaled to maxval."""
    maxval = max(float(maxval), 1.0)
    fill = int(round(min(float(value), maxval) / maxval * width))
    return "█" * fill + "░" * (width - fill)


def activity_rows(rows: list[tuple[str, str, float, float, str]]) -> str:
    """Stacked labelled activity bars (wifite-style), as rich markup.

    Each row is ``(label, colour, value, maxval, rate_text)``.
    """
    out = []
    for label, colour, value, maxval, rate in rows:
        bar = hbar(value, maxval)
        out.append(f"[dim]{label:<7}[/] [{colour}]{bar}[/] [dim]{rate:>8}[/]")
    return "\n".join(out)


def car_art(unlocked: bool) -> str:
    """A small pixel car (the target), coloured by lock state, as rich markup."""
    c = "green" if unlocked else "red"
    # Note: a backslash must never sit directly before a markup tag ("\[" escapes
    # the bracket in rich), so lines end on "/" or "_", not "\".
    return (
        f"[{c}]        ______________[/]\n"
        f"[{c}]    ___/[/] [b]C A R B O N[/] [{c}]\\_[/]\n"
        f"[{c}]   \\__________________/[/]\n"
        f"[{c}]      (O)          (O)[/]"
    )


def ecu_info(surface: dict[str, Any]) -> str:
    """Compact ECU status (session, security, services) as rich markup."""
    sess = (surface or {}).get("session") or {}
    unlocked = bool(sess.get("unlocked"))
    active = sess.get("active") or "-"
    nodes = (surface or {}).get("nodes") or []
    nsvc = sum(1 for n in nodes if n.get("type") == "service")
    lock = "[b green]deverrouille[/]" if unlocked else "[b red]verrouille[/]"
    return (f"[b]ECU 0x7E8[/]   [dim]7E0->7E8[/]\n"
            f"[dim]session  [/] {active}\n"
            f"[dim]securite [/] {lock}\n"
            f"[dim]services [/] {nsvc}")


def action_card(m: dict[str, Any], last: dict[str, Any] | None = None) -> str:
    """The central 'what am I doing' card: which tool, why, the result, what next.

    Reads as a labelled form (clear for a beginner) but stays dense (fine for an
    expert). Works in both guided and libre mode.
    """
    cur = m["current"]
    guided = m["mode"] == "guided"
    tool = cur.get("tool")
    cands = m.get("candidates") or []

    head = ("[b yellow]ACCOMPAGNE[/]" if guided else "[b]LIBRE[/]")
    lines = [f"{head}   [dim]etape[/]  {cur['title']}", ""]
    lines.append(f"[dim]outil   [/] [b cyan]{tool or '(etape a valider - touche a)'}[/]")
    if guided and cur.get("objective"):
        lines.append(f"[dim]but     [/] {cur['objective'].strip()}")
    if last is not None:
        ok = bool(last.get("ok"))
        colour, mark = ("green", "✓") if ok else ("red", "✗")
        lines.append(f"[dim]resultat[/] [{colour}]{mark} {last.get('tool')} : "
                     f"{interpret(last)}[/]")
    if guided:
        nxt = ", ".join(c.get("tool") or c.get("id") for c in cands) or "fin du parcours"
        lines.append(f"[dim]suite   [/] [cyan]-> {nxt}[/]")
    else:
        sugg = ", ".join(f"{c['id']}" for c in cands) or "-"
        lines.append(f"[dim]suite   [/] [cyan]lance un outil (c)[/]   "
                     f"[dim]suggere : {sugg}[/]")
    return "\n".join(lines)


def journal_block(ts: str, entries: list[str], ok: bool) -> str:
    """One journal entry as a small tree (wifite-style connectors)."""
    colour = "green" if ok else "red"
    lines = [f"[dim]{ts}[/] [{colour}]{entries[0]}[/]"]
    mid, last = entries[1:-1], entries[1:]
    for e in mid:
        lines.append(f"       [dim]|[/] [{colour}]{e}[/]")
    if len(entries) > 1:
        lines.append(f"       [dim]`[/] [{colour}]{entries[-1]}[/]")
    return "\n".join(lines)


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
        return (f"✓  SÉCURITÉ DÉVERROUILLÉE - niveau {data.get('level', '?')}", "banner-ok")
    if tool == "uds_clear_dtc":
        return ("✓  DTC EFFACÉS", "banner-ok")
    if tool == "uds_read_did":
        return (f"✓  DID 0x{_as_int(data.get('did')):X} LU - {data.get('value', '?')}", "banner-ok")
    return None


def journal_entries(result: dict[str, Any]) -> list[str]:
    """One or more plain log lines for a result.

    Seed-key is expanded into its challenge/response sequence (requestSeed ->
    sendKey -> unlocked), which reads like wifite3's M1->M8 handshake; every other
    tool is a single interpreted line.
    """
    tool = result.get("tool", "")
    ok = bool(result.get("ok"))
    data = result.get("data") or {}
    if tool == "uds_security_access":
        seed = data.get("seed", "?")
        lines = [f"seed-key : requestSeed -> seed {seed}", "  clé calculée -> sendKey"]
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
