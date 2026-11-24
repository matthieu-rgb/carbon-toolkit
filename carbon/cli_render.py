# SPDX-License-Identifier: GPL-3.0-or-later
"""Presentation layer for the ``carbon`` CLI: result panels and the dashboard.

Pure presentation. It reads the journal and derives a suggested next step; it
never runs a tool (the single execution path stays in ``execute_tool``). Output
is prettified only for an interactive terminal — the caller gates on
``isatty()`` and keeps the plain summary line for pipes, so scripts and tests
are unaffected.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["suggest_next", "read_journal", "make_console", "render_result", "render_dashboard"]

# Ordered CAN/UDS flow. Each entry: (tool that should already be ok, command, why).
# Used both after a tool runs and on the no-command dashboard, so the suggestion
# is consistent everywhere.
_FLOW: list[tuple[str, str, str]] = [
    ("uds_scan", "carbon uds_scan", "Découvrir les services du calculateur"),
    ("uds_session", "carbon uds_session", "Ouvrir la session de diagnostic étendue"),
    ("uds_security_access", "carbon uds_security_access",
     "Déverrouiller l'accès de sécurité (seed-key)"),
    ("uds_read_dtc", "carbon uds_read_dtc", "Lire les codes défaut (DTC)"),
]
_ALL_DONE = ("carbon uds_clear_dtc --yes",
             "Effacer les DTC (destructif : confirmation requise)")

_COMMANDS = "can_* · uds_* · emu · tui · web · mcp"


def suggest_next(history: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (command, why) for the next step, from the tools already run ``ok``.

    History entries need only a ``tool`` name and an ``ok`` flag (the journal's
    own shape), so this works whether the caller reads the journal or a session.
    """
    done = {h.get("tool") for h in history if h.get("ok")}
    for tool, cmd, why in _FLOW:
        if tool not in done:
            return cmd, why
    return _ALL_DONE


def read_journal(path: Path) -> list[dict[str, Any]]:
    """Parse the JSONL journal into entries; a missing file or bad line is skipped."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def make_console(stream: Any = None):
    """A Rich console bound to ``stream`` (defaults to stdout)."""
    from rich.console import Console

    return Console(file=stream, highlight=False, emoji=False)


def _duration(result) -> str | None:
    """Elapsed time of a ToolResult (its timestamps are datetimes)."""
    try:
        secs = (result.ended_at - result.started_at).total_seconds()
    except (AttributeError, TypeError):
        return None
    return f"{secs:.2f} s" if secs >= 0 else None


def _clock(ts: str | None) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S") if ts else "--:--:--"
    except (TypeError, ValueError):
        return "--:--:--"


def render_result(console, result, history: list[dict[str, Any]]) -> None:
    """Print one tool result as a bordered panel, with the suggested next step.

    ``result`` is a ToolResult (``.tool``, ``.ok``, ``.summary``, timestamps).
    ``history`` is the journal so far (including this result) for the suggestion.
    """
    from rich.panel import Panel
    from rich.text import Text

    ok = bool(result.ok)
    accent = "green" if ok else "red"
    mark = "✓" if ok else "✗"

    body = Text()
    body.append(result.summary or "", style="default")

    cmd, why = suggest_next(history)
    body.append("\n\n")
    body.append("→ Prochain  ", style="dim")
    body.append(cmd, style=f"bold {accent}")
    body.append(f"   {why}", style="dim")

    dur = _duration(result)
    console.print(Panel(
        body,
        title=Text(f"{mark} {result.tool}", style=f"bold {accent}"),
        title_align="left",
        subtitle=(Text(dur, style="dim") if dur else None),
        subtitle_align="right",
        border_style=accent,
        padding=(1, 2),
    ))


def render_dashboard(console, *, channel: str, interface: str,
                     journal_path: Path, version: str) -> None:
    """Print the no-command dashboard: session glance, recent actions, next step."""
    from rich.table import Table
    from rich.text import Text

    history = read_journal(journal_path)

    title = Text()
    title.append("CARBON", style="bold")
    title.append("  banc de pentest automobile", style="default")
    title.append(f"  v{version}", style="dim")
    console.print()
    console.print(title)
    console.print(
        Text(f"bus {channel} · interface {interface} · journal {journal_path}", style="dim")
    )
    console.print()

    if history:
        console.print(Text("Dernières actions", style="bold"))
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim", no_wrap=True)       # time
        table.add_column(no_wrap=True)                     # mark
        table.add_column(style="bold", no_wrap=True)       # tool
        table.add_column(style="default")                  # summary
        for h in history[-5:]:
            ok = bool(h.get("ok"))
            table.add_row(
                _clock(h.get("ts")),
                Text("✓" if ok else "✗", style="green" if ok else "red"),
                str(h.get("tool", "?")),
                str(h.get("summary", "")),
            )
        console.print(table)
    else:
        intro = Text()
        intro.append("Aucune session encore. Pour commencer, sans matériel :\n", style="default")
        intro.append("  1.  ", style="dim")
        intro.append("carbon emu start", style="bold cyan")
        intro.append("        lance un calculateur simulé\n", style="dim")
        intro.append("  2.  ", style="dim")
        intro.append("carbon uds_scan", style="bold cyan")
        intro.append("          découvre ses services", style="dim")
        console.print(intro)

    cmd, why = suggest_next(history)
    console.print()
    nxt = Text()
    nxt.append("Prochaine étape conseillée\n", style="bold")
    nxt.append("  → ", style="dim")
    nxt.append(cmd, style="bold green")
    nxt.append(f"\n     {why}", style="dim")
    console.print(nxt)

    console.print()
    console.print(Text(f"Commandes   {_COMMANDS}", style="dim"))
    console.print(Text("Aide        carbon COMMANDE --help   ·   carbon doctor", style="dim"))
    console.print()
