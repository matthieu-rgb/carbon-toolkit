# SPDX-License-Identifier: GPL-3.0-or-later
"""CARBON TUI. Façade only: every decision lives in Session / Engine (O7)."""
from __future__ import annotations

import json
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, OptionList, Static

from carbon.core.execute import Decision, Origin
from carbon.core.result import ToolResult
from carbon.mcp.approval import ApprovalQueue, PendingApproval


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
    #choices, #tools { height: auto; max-height: 12; }
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

    # ---- layout -----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="step")
        yield Static(id="status")
        yield OptionList(id="choices")
        yield OptionList(id="tools")
        yield Input(placeholder="paramètres : clé=valeur ...", id="params")
        yield Static("(aucun résultat)", id="result")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_view()

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
        m = self.session.state()["methodology"]
        step_w, status_w = self.query_one("#step", Static), self.query_one("#status", Static)
        choices, tools = self.query_one("#choices", OptionList), self.query_one("#tools", OptionList)
        params = self.query_one("#params", Input)
        if not m.get("loaded"):
            step_w.update("Aucune méthodologie chargée.")
            status_w.update("")
            choices.display = tools.display = params.display = False
            return
        cur = m["current"]
        guided = m["mode"] == "guided"
        self.sub_title = f"mode {'guidé' if guided else 'libre'}"
        lines = [f"[b]{cur['title']}[/b]", cur["objective"].strip(),
                 f"outil suggéré : {cur['tool'] or '(étape informative, touche a)'}"]
        if not guided:
            lines.insert(0, "[b]Vue libre[/b] — position du parcours :")
            sugg = ", ".join(f"{c['id']} ({c['tool'] or 'info'})" for c in m["candidates"])
            lines.append(f"suggestions (non bloquantes) : {sugg or '-'}")
        step_w.update("\n".join(lines))
        status_w.update(f"étape {cur['id']} — "
                        + ("satisfaite" if m["satisfied"] else "non satisfaite"))
        choices.clear_options()
        show_choices = bool(m["pending_choice"])
        if show_choices:
            for c in m["candidates"]:
                choices.add_option(f"{c['id']} — {c['title']}")
        choices.display = show_choices
        tools.clear_options()
        tools.display = not guided
        if not guided:
            for name in self.session.state()["tools"]:
                tools.add_option(name)
        step = self.session.engine.current()
        params.display = (not guided) or bool(step.prompt_params)
        params.placeholder = ("paramètres : " + " ".join(f"{p}=…" for p in step.prompt_params)
                              if step.prompt_params else "paramètres : clé=valeur ...")

    def _show_result(self, text: str) -> None:
        self.query_one("#result", Static).update(text)

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
        self._show_result(f"exécution de {tool}…")
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

    def _run_failed(self, tool: str, exc: Exception) -> None:
        self.busy = False
        self._show_result(f"{tool} : erreur {exc}")
        self.refresh_view()

    def _run_done(self, result: ToolResult) -> None:
        self.busy = False
        self.last_result = result
        data = json.dumps(result.data, ensure_ascii=False, indent=2, default=str)
        self._show_result(
            f"{result.tool} : {'OK' if result.ok else 'ÉCHEC'}\n{result.summary}\n{data}")
        self.refresh_view()
