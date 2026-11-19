# SPDX-License-Identifier: GPL-3.0-or-later
"""`carbon` command line: registry -> authorization guard -> run -> journal."""
from __future__ import annotations

import sys
from pathlib import Path

import click

from carbon.can.bus import BusUnavailableError
from carbon.core.confirm import authorize
from carbon.core.journal import Journal, JournalError
from carbon.core.registry import Registry
from carbon.tools.can_dump import CanDump
from carbon.tools.can_inject import CanInject
from carbon.tools.can_replay import CanReplay
from carbon.tools.can_sniff import CanSniff

DEFAULT_JOURNAL = "carbon-session.jsonl"  # relative to the current directory
ACTOR = "cli"


def build_registry() -> Registry:
    """Single place where adapters are registered."""
    registry = Registry()
    for adapter in (CanSniff(), CanDump(), CanReplay(), CanInject()):
        registry.register(adapter)
    return registry


def _hex_bytes(_ctx, _param, value: str | None) -> bytes:
    try:
        return bytes.fromhex(value or "")
    except ValueError:
        raise click.BadParameter(f"not valid hex: {value!r}")


def _hex_id(_ctx, _param, value: str) -> int:
    try:
        return int(value, 16)
    except ValueError:
        raise click.BadParameter(f"not a hex arbitration id: {value!r}")


# Extra click params per adapter name; the CLI maps them to run() kwargs.
_PARAMS: dict[str, list[click.Parameter]] = {
    "can_sniff": [
        click.Option(["--count"], type=int, default=None, help="Stop after N frames."),
        click.Option(["--timeout"], type=float, default=1.0, show_default=True),
    ],
    "can_dump": [
        click.Argument(["path"]),
        click.Option(["--count"], type=int, default=None, help="Stop after N frames."),
        click.Option(["--timeout"], type=float, default=1.0, show_default=True),
    ],
    "can_replay": [click.Argument(["path"])],
    "can_inject": [
        click.Argument(["arb_id"], callback=_hex_id),
        click.Argument(["data"], callback=_hex_bytes, required=False, default=""),
        click.Option(["--extended"], is_flag=True, help="Use a 29-bit identifier."),
    ],
}


def _make_command(adapter) -> click.Command:
    @click.pass_context
    def callback(ctx: click.Context, **params):
        g = ctx.obj
        if not authorize(
            adapter, assume_yes=g["yes"], interactive=sys.stdin.isatty()
        ):
            raise click.ClickException(
                f"{adapter.name} is destructive: refused (use --yes to authorize)"
            )
        run_params = {"channel": g["channel"], "interface": g["interface"], **params}
        try:
            result = adapter.run(**run_params)
        except (BusUnavailableError, ValueError, OSError) as exc:
            raise click.ClickException(str(exc))
        try:
            Journal(g["journal"]).record(result, _jsonable(run_params), ACTOR)
        except JournalError as exc:
            raise click.ClickException(str(exc))
        click.echo(result.summary)
        if not result.ok:
            ctx.exit(1)

    doc = (type(adapter).__doc__ or "").strip() or f"Run {adapter.name}."
    if adapter.destructive:
        doc += " (destructive: needs --yes or confirmation)"
    return click.Command(
        adapter.name, params=list(_PARAMS.get(adapter.name, [])), callback=callback, help=doc
    )


def _jsonable(params: dict) -> dict:
    return {k: (v.hex() if isinstance(v, bytes) else v) for k, v in params.items()}


def build_cli(registry: Registry | None = None) -> click.Group:
    registry = registry or build_registry()

    @click.group(help="CARBON automotive pentest toolkit.")
    @click.option("--channel", default="vcan0", show_default=True)
    @click.option("--interface", default="socketcan", show_default=True)
    @click.option(
        "--journal", type=click.Path(path_type=Path), default=Path(DEFAULT_JOURNAL),
        show_default=True, help="Audit journal (JSONL, append-only).",
    )
    @click.option("--yes", is_flag=True, help="Authorize destructive actions without prompting.")
    @click.pass_context
    def group(ctx, channel, interface, journal, yes):
        ctx.obj = {"channel": channel, "interface": interface, "journal": journal, "yes": yes}

    for name in registry.names():
        group.add_command(_make_command(registry.get(name)))
    return group


main = build_cli()

if __name__ == "__main__":
    main()
