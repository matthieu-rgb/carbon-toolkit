# SPDX-License-Identifier: GPL-3.0-or-later
"""`carbon ctf`: list, start, submit, hint, status, reset — a local challenge runner.

Presentation + progress only; challenges are solved with CARBON's own tools and
validated by deterministic flag match. No new execution path.
"""
from __future__ import annotations

from pathlib import Path

import click

from carbon.cli_render import make_console
from carbon.ctf.catalog import AVAILABLE, LOCKED, SOLVED, bundled_challenges, status_of
from carbon.ctf.model import Challenge, check_flag
from carbon.ctf.progress import Progress, default_progress_path, load_progress

_STATUS_STYLE = {SOLVED: "green", AVAILABLE: "bold", LOCKED: "dim"}
_STATUS_MARK = {SOLVED: "✓ résolu", AVAILABLE: "• dispo", LOCKED: "🔒 verrouillé"}


def _load(ctx) -> tuple[list[Challenge], Progress]:
    return bundled_challenges(), load_progress(ctx.obj["ctf_progress"])


def _find(challenges: list[Challenge], cid: str) -> Challenge:
    for c in challenges:
        if c.id == cid:
            return c
    raise click.ClickException(f"challenge inconnu : {cid!r} (voir « carbon ctf list »)")


def build_ctf_group() -> click.Group:
    @click.group("ctf", help="Parcours CTF sur le calculateur simulé.")
    @click.option("--progress", "progress", type=click.Path(path_type=Path), default=None,
                  help="Fichier de progression (défaut : ~/.carbon/ctf_progress.json).")
    @click.pass_context
    def ctf(ctx, progress):
        ctx.ensure_object(dict)
        ctx.obj["ctf_progress"] = progress or default_progress_path()

    @ctf.command("list", help="Lister les challenges et leur état.")
    @click.option("--category", default=None)
    @click.option("--difficulty", default=None)
    @click.pass_context
    def list_cmd(ctx, category, difficulty):
        from rich.table import Table

        challenges, prog = _load(ctx)
        table = Table(box=None, pad_edge=False, padding=(0, 2))
        table.add_column("")
        table.add_column("id", no_wrap=True)
        table.add_column("titre")
        table.add_column("catégorie", no_wrap=True)
        table.add_column("diff.", no_wrap=True)
        table.add_column("état", no_wrap=True)
        for c in challenges:
            if category and c.category != category:
                continue
            if difficulty and c.difficulty != difficulty:
                continue
            st = status_of(c, prog)
            style = _STATUS_STYLE[st]
            table.add_row(f"[{style}]{'✓' if st == SOLVED else ' '}[/]",
                          f"[{style}]{c.id}[/]", f"[{style}]{c.title}[/]",
                          c.category, c.difficulty, f"[{style}]{_STATUS_MARK[st]}[/]")
        console = make_console()
        console.print(table)
        done = len(prog.solved_ids() & {c.id for c in challenges})
        console.print(f"[dim]{done}/{len(challenges)} résolus · "
                      f"« carbon ctf start <id> » pour commencer[/]")

    @ctf.command("start", help="Afficher le briefing d'un challenge.")
    @click.argument("cid")
    @click.pass_context
    def start_cmd(ctx, cid):
        from rich.panel import Panel

        challenges, prog = _load(ctx)
        c = _find(challenges, cid)
        if status_of(c, prog) == LOCKED:
            raise click.ClickException(
                f"{cid} est verrouillé — résous d'abord : {', '.join(c.requires)}")
        scope = ", ".join(c.target.get("in_scope", []))
        body = c.briefing + (f"\n\n[dim]Outils en jeu : {scope}[/]" if scope else "")
        make_console().print(Panel(body, title=f"[bold]{c.title}[/]  ·  {c.category}/{c.difficulty}",
                                   title_align="left", border_style="cyan", padding=(1, 2)))

    @ctf.command("submit", help="Soumettre un flag.")
    @click.argument("cid")
    @click.argument("flag")
    @click.pass_context
    def submit_cmd(ctx, cid, flag):
        challenges, prog = _load(ctx)
        c = _find(challenges, cid)
        console = make_console()
        if status_of(c, prog) == LOCKED:
            raise click.ClickException(
                f"{cid} est verrouillé — résous d'abord : {', '.join(c.requires)}")
        if check_flag(c, flag):
            before = {x.id for x in challenges if status_of(x, prog) == AVAILABLE}
            prog.mark_solved(c.id)
            after = {x.id for x in challenges if status_of(x, prog) == AVAILABLE}
            console.print(f"[green]✓ Correct ![/] [b]{c.title}[/] résolu (+{c.points} pts).")
            newly = sorted(after - before)
            if newly:
                console.print(f"[cyan]Débloqué :[/] {', '.join(newly)}")
        else:
            prog.record_attempt(c.id)
            console.print(f"[red]✗ Flag incorrect.[/] Réessaie — « carbon ctf hint {cid} » "
                          f"pour un indice.")
            ctx.exit(1)

    @ctf.command("hint", help="Révéler l'indice suivant.")
    @click.argument("cid")
    @click.pass_context
    def hint_cmd(ctx, cid):
        challenges, prog = _load(ctx)
        c = _find(challenges, cid)
        console = make_console()
        used = prog.hints_used(c.id)
        if used >= len(c.hints):
            console.print("[dim]Plus d'indice disponible pour ce challenge.[/]")
            return
        hint = c.hints[used]
        prog.reveal_hint(c.id)
        cost = f" [dim](coût {hint.cost})[/]" if hint.cost else ""
        console.print(f"[yellow]Indice {used + 1}/{len(c.hints)}[/]{cost} : {hint.text}")

    @ctf.command("status", help="Résumé de progression.")
    @click.pass_context
    def status_cmd(ctx):
        challenges, prog = _load(ctx)
        console = make_console()
        solved = prog.solved_ids() & {c.id for c in challenges}
        pts = sum(c.points for c in challenges if c.id in solved)
        console.print(f"[b]Progression[/] : {len(solved)}/{len(challenges)} résolus · {pts} pts")
        cats: dict[str, list[int]] = {}
        for c in challenges:
            d, t = cats.setdefault(c.category, [0, 0]), None
            d[1] += 1
            if c.id in solved:
                d[0] += 1
        for cat, (done, total) in sorted(cats.items()):
            console.print(f"  [dim]{cat:<16}[/] {done}/{total}")

    @ctf.command("reset", help="Réinitialiser un challenge.")
    @click.argument("cid")
    @click.pass_context
    def reset_cmd(ctx, cid):
        challenges, prog = _load(ctx)
        c = _find(challenges, cid)
        prog.reset(c.id)
        make_console().print(f"[dim]{c.id} réinitialisé.[/]")

    return ctf
