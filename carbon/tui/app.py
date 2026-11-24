# SPDX-License-Identifier: GPL-3.0-or-later
"""CARBON TUI. Façade only: every decision lives in Session / Engine (O7)."""
from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, OptionList, Static

from carbon.can.bus import open_bus
from carbon.core.execute import Decision, Origin
from carbon.core.result import ToolResult
from carbon.mcp.approval import ApprovalQueue, PendingApproval
from carbon.tui.present import (
    action_card,
    activity_rows,
    banner_for,
    car_art,
    ecu_info,
    journal_block,
    journal_entries,
    progress_rail,
    services_from_surface,
)


def parse_params(text: str) -> dict[str, Any]:
    """Parse ``key=value key=value`` (values: JSON, then int/hex, else string)."""
    out: dict[str, Any] = {}
    for tok in text.split():
        if "=" not in tok:
            raise ValueError(f"paramètre mal formé: {tok!r} (attendu clé=valeur)")
        k, v = tok.split("=", 1)
        try:
            out[k] = json.loads(v)
        except ValueError:
            try:
                out[k] = int(v, 0)
            except ValueError:
                out[k] = v
    return out


class _MeterSniffer:
    """Background CAN reader that counts frames, so the rx meter reflects live bus
    traffic (not only tool runs). Read-only: its own bus handle, never writes. If
    the bus cannot be opened, it exits quietly and meters stay tool-driven.
    """

    def __init__(self, channel: str, interface: str, on_frame) -> None:
        self._channel, self._interface, self._on_frame = channel, interface, on_frame
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="meter-sniff")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        try:
            bus = open_bus(self._channel, self._interface)
        except Exception:
            return
        try:
            while not self._stop.is_set():
                try:
                    msg = bus.recv(timeout=0.2)
                except Exception:
                    break
                if msg is not None:
                    self._on_frame()
        finally:
            try:
                bus.shutdown()
            except Exception:
                pass


class ApprovalModal(ModalScreen[Decision]):
    """Lists one pending destructive action; Approve / Deny."""

    BINDINGS = [Binding("y", "approve", "Approuver"), Binding("n", "deny", "Refuser")]

    def __init__(self, pending: PendingApproval) -> None:
        super().__init__()
        self.pending = pending

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-box"):
            yield Static("Action destructrice en attente d'approbation", id="approval-title")
            yield Static(f"outil : {self.pending.tool}\nparamètres : {self.pending.params}",
                         id="approval-body")
            with Horizontal():
                yield Button("Approuver (y)", id="approve", variant="success")
                yield Button("Refuser (n)", id="deny", variant="error")

    def action_approve(self) -> None:
        self.dismiss(Decision.APPROVED)

    def action_deny(self) -> None:
        self.dismiss(Decision.DENIED)

    @on(Button.Pressed, "#approve")
    def _approve(self) -> None:
        self.action_approve()

    @on(Button.Pressed, "#deny")
    def _deny(self) -> None:
        self.action_deny()


class CarbonApp(App):
    TITLE = "CARBON"
    CSS = """
    ApprovalModal { align: center middle; }
    #approval-box { width: 70; height: auto; border: heavy $warning; padding: 1 2;
                    background: $surface; }
    #banner { display: none; height: 1; text-align: center; text-style: bold; }
    #banner.banner-ok { display: block; background: $success; color: $text; }
    #progress { padding: 1 1 0 1; height: 2; color: $text; }
    #instrument { height: 6; padding: 0 1; }
    #car { width: 28; content-align: left middle; }
    #activity { width: 1fr; padding: 1 2; content-align: left middle; }
    #ecu { width: 32; border: round $primary; padding: 0 1; }
    #main-row { height: 1fr; }
    #left-col { width: 2fr; padding: 0 1; }
    #right-col { width: 1fr; padding: 0 1; }
    #step { border: round $accent; padding: 1 2; height: auto; }
    #status { color: $text-muted; padding: 0 2; height: 1; }
    #choices, #tools { height: auto; max-height: 10; }
    #result { color: $text-muted; height: auto; }
    .panel-title { text-style: bold; color: $accent; padding: 1 0 0 0; }
    #services { border: round $primary; padding: 0 1; height: auto; min-height: 5; }
    #journal { border: round $primary-darken-1; padding: 0 1; height: 1fr; }
    """
    BINDINGS = [
        Binding("r", "run", "Exécuter"),
        Binding("a", "ack", "Valider l'étape"),
        Binding("m", "toggle_mode", "Guidé/Libre"),
        Binding("p", "focus_params", "Paramètres"),
        Binding("c", "focus_list", "Choix/Outils"),
        Binding("q", "quit", "Quitter"),
    ]

    def __init__(self, session, queue: ApprovalQueue | None = None) -> None:
        super().__init__()
        self.session = session
        self.queue = queue if queue is not None else session.approver
        self.busy = False
        self.last_result: ToolResult | None = None
        self.journal_lines: list[str] = []
        self.meters: dict[str, deque] = {
            k: deque([0] * 12, maxlen=24) for k in ("rx", "uds", "inject")}
        self._bucket: dict[str, int] = {"rx": 0, "uds": 0, "inject": 0}
        self._sniffer: _MeterSniffer | None = None

    # ---- layout -----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="banner")
        yield Static(id="progress")
        with Horizontal(id="instrument"):
            yield Static(id="car")
            yield Static(id="activity")
            yield Static(id="ecu")
        with Horizontal(id="main-row"):
            with Vertical(id="left-col"):
                yield Static(id="step")
                yield Static(id="status")
                yield OptionList(id="choices")
                yield OptionList(id="tools")
                yield Input(placeholder="paramètres : clé=valeur ...", id="params")
                yield Static("(aucun résultat)", id="result")
            with Vertical(id="right-col"):
                yield Static("SERVICES", classes="panel-title")
                yield Static("(rien découvert)", id="services")
                yield Static("JOURNAL", classes="panel-title")
                yield Static("", id="journal")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_view()
        self._render_activity()
        self.set_interval(0.5, self._tick)
        # The passive rx sniffer attaches only to an out-of-process bus. The
        # in-process "virtual" bus shares one queue, so a second consumer would
        # steal/reorder frames from the tools themselves (and the tests).
        if self.session.interface != "virtual":
            self._sniffer = _MeterSniffer(
                self.session.channel, self.session.interface, self._on_sniff_frame)
            self._sniffer.start()

    def on_unmount(self) -> None:
        if self._sniffer is not None:
            self._sniffer.stop()

    def _on_sniff_frame(self) -> None:
        self._bucket["rx"] += 1  # from the sniffer thread; plain int add is atomic

    # ---- live meters ------------------------------------------------------
    def _tick(self) -> None:
        for k, buf in self.meters.items():
            buf.append(self._bucket[k])
            self._bucket[k] = 0
        self._render_activity()

    def _render_activity(self) -> None:
        try:
            w = self.query_one("#activity", Static)
        except NoMatches:
            return  # timer may fire during mount/unmount transitions
        m = self.meters
        peak = max([max(buf) for buf in m.values()] + [1])

        def latest(k: str) -> int:
            return m[k][-1] if m[k] else 0

        rows = [
            ("CAN rx", "green", latest("rx"), peak, f"{latest('rx') * 2} /s"),
            ("UDS", "cyan", latest("uds"), peak, f"{latest('uds') * 2} /s"),
            ("inject", "yellow", latest("inject"), peak, f"{latest('inject') * 2} /s"),
        ]
        w.update(activity_rows(rows))

    # ---- approval bridge (called from the approver thread) ----------------
    def on_pending(self, pending: PendingApproval) -> None:
        """ApprovalQueue.on_pending hook: hop to the UI thread, show the modal."""
        self.call_from_thread(self._show_approval, pending)

    def _show_approval(self, pending: PendingApproval) -> None:
        def done(decision: Decision | None) -> None:
            if self.queue is not None:
                self.queue.resolve(
                    pending.id, decision if decision is not None else Decision.DENIED)

        self.push_screen(ApprovalModal(pending), done)

    # ---- view -------------------------------------------------------------
    def refresh_view(self) -> None:
        st = self.session.state()
        m = st["methodology"]
        step_w, status_w = self.query_one("#step", Static), self.query_one("#status", Static)
        choices, tools = self.query_one("#choices", OptionList), self.query_one("#tools", OptionList)
        params = self.query_one("#params", Input)
        surf = st.get("surface") or {}
        self._refresh_services(surf)
        sess = surf.get("session") or {}
        self.query_one("#ecu", Static).update(ecu_info(surf))
        self.query_one("#car", Static).update(car_art(bool(sess.get("unlocked"))))
        if not m.get("loaded"):
            self.query_one("#progress", Static).update("")
            step_w.update("Aucune méthodologie chargée.")
            status_w.update("")
            choices.display = tools.display = params.display = False
            return
        cur = m["current"]
        guided = m["mode"] == "guided"
        self.sub_title = f"mode {'accompagné' if guided else 'libre'}"
        self.query_one("#progress", Static).update(progress_rail(cur["title"]))
        last = self.last_result.to_dict() if self.last_result is not None else None
        step_w.update(action_card(m, last))
        status_w.update(f"étape {cur['id']} - "
                        + ("satisfaite" if m["satisfied"] else "non satisfaite"))
        choices.clear_options()
        show_choices = bool(m["pending_choice"])
        if show_choices:
            for c in m["candidates"]:
                choices.add_option(f"{c['id']} - {c['title']}")
        choices.display = show_choices
        tools.clear_options()
        tools.display = not guided
        if not guided:
            for name in self.session.state()["tools"]:
                tools.add_option(name)
        step = self.session.engine.current()
        params.display = (not guided) or bool(step.prompt_params)
        params.placeholder = ("paramètres : " + " ".join(f"{p}=..." for p in step.prompt_params)
                              if step.prompt_params else "paramètres : clé=valeur ...")

    def _show_result(self, text: str) -> None:
        self.query_one("#result", Static).update(text)

    def _refresh_services(self, surface: dict) -> None:
        rows = services_from_surface(surface)
        w = self.query_one("#services", Static)
        if not rows:
            w.update("[dim](rien découvert)[/]")
            return
        lines = []
        for r in rows:
            name = f"  [dim]{r['name']}[/]" if r["name"] else ""
            lines.append(f"[b]{r['label']}[/]{name}")
        w.update("\n".join(lines))

    # ---- actions ----------------------------------------------------------
    def action_toggle_mode(self) -> None:
        new = "libre" if self.session.mode == "guided" else "guided"
        self.session.set_mode(new)
        self.refresh_view()

    def action_ack(self) -> None:
        try:
            self.session.step_ack()
        except Exception as exc:  # engine refuses: report, do not crash the UI
            self._show_result(f"validation impossible : {exc}")
        self.refresh_view()

    def action_focus_params(self) -> None:
        self.query_one("#params", Input).focus()

    def action_focus_list(self) -> None:
        w = self.query_one("#choices" if self.query_one("#choices").display else "#tools")
        w.focus()

    @on(OptionList.OptionSelected, "#choices")
    def _choose(self, event: OptionList.OptionSelected) -> None:
        cand = self.session.state()["methodology"]["candidates"][event.option_index]
        try:
            self.session.step_choose(cand["id"])
        except Exception as exc:
            self._show_result(f"choix impossible : {exc}")
        self.refresh_view()

    @on(OptionList.OptionSelected, "#tools")
    def _tool_selected(self, event: OptionList.OptionSelected) -> None:
        self._start_run(self.session.state()["tools"][event.option_index], libre=True)

    @on(Input.Submitted, "#params")
    def _params_submitted(self) -> None:
        self.action_run()
        self.set_focus(None)

    def action_run(self) -> None:
        m = self.session.state()["methodology"]
        if m.get("loaded") and m["mode"] == "guided":
            if not m["current"]["tool"]:
                self._show_result("étape informative : valide-la avec la touche a")
                return
            self._start_run(m["current"]["tool"], libre=False)
        else:
            tools = self.query_one("#tools", OptionList)
            idx = tools.highlighted
            if idx is None:
                self._show_result("choisis un outil dans la liste (touche c)")
                return
            self._start_run(self.session.state()["tools"][idx], libre=True)

    def _start_run(self, tool: str, *, libre: bool) -> None:
        if self.busy:
            return
        try:
            params: dict[str, Any] = {}
            if not libre:
                params.update(self.session.engine.current().params)
            params.update(parse_params(self.query_one("#params", Input).value))
        except ValueError as exc:
            self._show_result(str(exc))
            return
        self.busy = True
        self._show_result(f"exécution de {tool}...")
        self.run_worker(lambda: self._run_blocking(tool, params), thread=True,
                        name=f"run-{tool}")

    def _run_blocking(self, tool: str, params: dict[str, Any]) -> None:
        # Worker thread: run_tool may block on the approval queue (modal).
        try:
            result = self.session.run_tool(tool, origin=Origin.TUI, **params)
        except Exception as exc:
            self.call_from_thread(self._run_failed, tool, exc)
            return
        self.call_from_thread(self._run_done, result)

    def _bump_meter(self, result: ToolResult) -> None:
        # rx is fed live by the background sniffer; here only the semantic counters.
        tool, data = result.tool, (result.data or {})
        if tool == "can_inject":
            self._bucket["inject"] += 1
        elif tool == "can_replay":
            self._bucket["inject"] += int(data.get("frames") or 0) or 1
        elif tool.startswith("uds_"):
            self._bucket["uds"] += 1

    def _run_failed(self, tool: str, exc: Exception) -> None:
        self.busy = False
        self._show_result(f"{tool} : erreur {exc}")
        self.refresh_view()

    def _run_done(self, result: ToolResult) -> None:
        self.busy = False
        self.last_result = result
        d = result.to_dict()
        self._bump_meter(result)
        ts = datetime.now().strftime("%H:%M:%S")
        entries = journal_entries(d)
        self.journal_lines.append(journal_block(ts, entries, result.ok))
        self.journal_lines = self.journal_lines[-12:]
        self.query_one("#journal", Static).update("\n".join(self.journal_lines))
        milestone = banner_for(d)
        if milestone:
            text, cls = milestone
            banner = self.query_one("#banner", Static)
            banner.remove_class("banner-ok")
            banner.add_class(cls)
            banner.update(text)
        self._show_result(
            f"{result.tool} : {'OK' if result.ok else 'ÉCHEC'} - {result.summary}")
        self.refresh_view()
