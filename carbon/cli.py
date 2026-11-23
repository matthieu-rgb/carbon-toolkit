# SPDX-License-Identifier: GPL-3.0-or-later
"""`carbon` command line: registry -> authorization guard -> run -> journal."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import click

from carbon.can.bus import BusError
from carbon.core.execute import ActionRefused, Origin, execute_tool
from carbon.core.journal import Journal, JournalError
from carbon.core.registry import Registry
from carbon.core.registry_builder import build_registry  # re-exported
from carbon.emu.ecu import EcuConfig, SimulatedEcu

DEFAULT_JOURNAL = "carbon-session.jsonl"  # relative to the current directory


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
    "uds_scan": [],
    "uds_session": [
        click.Option(
            ["--session"], type=click.Choice(["default", "extended"]),
            default="extended", show_default=True,
        ),
    ],
    "uds_security_access": [
        click.Option(["--level"], type=int, default=1, show_default=True),
    ],
    "uds_read_did": [
        click.Argument(["did"], callback=_hex_id, required=False, default="F190"),
    ],
    "uds_read_dtc": [
        click.Option(
            ["--status-mask"], callback=_hex_id, default="FF", show_default=True,
            help="DTC status mask (hex).",
        ),
    ],
    "uds_clear_dtc": [
        click.Option(
            ["--group"], callback=_hex_id, default="FFFFFF", show_default=True,
            help="DTC group (hex).",
        ),
    ],
}


def _make_command(adapter) -> click.Command:
    @click.pass_context
    def callback(ctx: click.Context, **params):
        g = ctx.obj
        run_params = {"channel": g["channel"], "interface": g["interface"], **params}
        try:
            result = execute_tool(
                adapter, run_params, origin=Origin.CLI, journal=Journal(g["journal"]),
                assume_yes=g["yes"], interactive=sys.stdin.isatty(),
            )
        except ActionRefused:
            # Refusals are intentionally not journaled: nothing touched the bus.
            raise click.ClickException(
                f"{adapter.name} is destructive: refused (use --yes to authorize)"
            )
        except JournalError as exc:
            raise click.ClickException(f"{adapter.name} executed but {exc}")
        if sys.stdout.isatty():
            from carbon import cli_render
            history = cli_render.read_journal(g["journal"])
            cli_render.render_result(cli_render.make_console(), result, history)
        else:
            # Piped/non-interactive: keep the plain summary line so scripts and
            # tests that grep stdout are unaffected.
            click.echo(result.summary)
        if not result.ok:
            ctx.exit(1)

    doc = (type(adapter).__doc__ or "").strip() or f"Run {adapter.name}."
    if adapter.destructive:
        doc += " (destructive: needs --yes or confirmation)"
    return click.Command(
        adapter.name, params=list(_PARAMS.get(adapter.name, [])), callback=callback, help=doc
    )


def _build_emu_group() -> click.Group:
    """`carbon emu`: long-running simulated ECU (not a registry adapter, not journaled)."""

    @click.group("emu", help="Simulated ECU for practicing UDS safely.")
    def emu():
        pass

    @emu.command("start", help="Run the simulated ECU until Ctrl-C.")
    @click.option("--channel", default=None, help="Defaults to the global --channel.")
    @click.option("--seed", callback=_hex_bytes, default=None, help="Security seed (hex).")
    @click.pass_context
    def start(ctx, channel, seed):
        g = ctx.obj or {}
        channel = channel or g.get("channel", "vcan0")
        interface = g.get("interface", "socketcan")
        config = EcuConfig(seed=seed) if seed else EcuConfig()
        try:
            with SimulatedEcu(channel, interface, config=config) as ecu:
                click.echo(
                    f"Simulated ECU on {channel} ({interface}): "
                    f"request 0x{ecu.config.req_id:X} / response 0x{ecu.config.resp_id:X}"
                )
                click.echo("Ctrl-C to stop")
                try:
                    threading.Event().wait()
                except KeyboardInterrupt:
                    click.echo("Stopped.")
        except (BusError, OSError) as exc:
            raise click.ClickException(str(exc))

    return emu


def _build_mcp_group() -> click.Group:
    """`carbon mcp`: expose CARBON to an AI client over MCP."""

    @click.group("mcp", help="Model Context Protocol server.")
    def mcp():
        pass

    @mcp.command("serve", help="Serve CARBON over MCP (stdio or HTTP + Bearer token).")
    @click.option("--transport", type=click.Choice(["stdio", "http"]), default="stdio",
                  show_default=True)
    @click.option("--host", default="127.0.0.1", show_default=True,
                  help="HTTP bind address (loopback only).")
    @click.option("--port", type=int, default=8777, show_default=True)
    @click.pass_context
    def serve_cmd(ctx, transport, host, port):
        from carbon.mcp.transport import serve

        g = ctx.obj
        try:
            serve(
                transport=transport, channel=g["channel"], interface=g["interface"],
                journal_path=g["journal"], host=host, port=port,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc))
        except KeyboardInterrupt:
            pass

    return mcp


def _build_tui_command() -> click.Command:
    """`carbon tui`: Textual guided/libre UI over one in-process Session."""

    @click.command("tui", help="Interactive guided/libre terminal UI.")
    @click.option("--methodology", "methodology", required=True,
                  type=click.Path(exists=True, dir_okay=False, path_type=Path),
                  help="Methodology YAML to walk.")
    @click.pass_context
    def tui_cmd(ctx, methodology):
        from carbon.core.session import Session
        from carbon.mcp.approval import ApprovalQueue
        from carbon.tui import CarbonApp

        g = ctx.obj
        try:
            session = open_guided_session(
                Session, methodology, channel=g["channel"],
                interface=g["interface"], journal_path=g["journal"])
        except Exception as exc:
            raise click.ClickException(str(exc))
        app = CarbonApp(session)
        # Approvals surface in the TUI modal; no stdin console thread under a TUI.
        app.queue = session.approver = ApprovalQueue(on_pending=app.on_pending)
        app.run()

    return tui_cmd


def _build_web_command() -> click.Command:
    """`carbon web`: localhost Web client + MCP on one shared Session."""

    @click.command("web", help="Localhost Web client (also serves /mcp with Bearer token).")
    @click.option("--host", default="127.0.0.1", show_default=True,
                  help="Bind address (loopback only).")
    @click.option("--port", type=int, default=8800, show_default=True)
    @click.option("--methodology", "methodology", default=None,
                  type=click.Path(exists=True, dir_okay=False, path_type=Path),
                  help="Optional methodology YAML (Web is Libre without it).")
    @click.pass_context
    def web_cmd(ctx, host, port, methodology):
        from carbon.web.serve import serve_web

        g = ctx.obj
        if methodology is not None:
            click.echo("note: --methodology is not yet used by the Web client", err=True)
        try:
            serve_web(channel=g["channel"], interface=g["interface"],
                      journal_path=g["journal"], host=host, port=port)
        except ValueError as exc:
            raise click.ClickException(str(exc))
        except KeyboardInterrupt:
            pass

    return web_cmd


def open_guided_session(session_cls, methodology: Path, *, channel: str,
                        interface: str, journal_path: Path, approver=None):
    """Fresh session, or resume the saved position if the state file exists."""
    state_path = journal_path.with_suffix(".state.json")
    if state_path.exists():
        return session_cls.resume(state_path, channel=channel, interface=interface,
                                  journal_path=journal_path, approver=approver)
    session = session_cls(channel=channel, interface=interface,
                          journal_path=journal_path, approver=approver,
                          state_path=state_path)
    session.load_methodology(methodology)
    return session


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("carbon")
    except Exception:
        return "0.6.0"


def build_cli(registry: Registry | None = None) -> click.Group:
    registry = registry or build_registry()

    @click.group(help="CARBON automotive pentest toolkit.", invoke_without_command=True)
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
        if ctx.invoked_subcommand is None:
            # No subcommand: show the dashboard instead of a bare usage dump.
            from carbon import cli_render

            cli_render.render_dashboard(
                cli_render.make_console(), channel=channel, interface=interface,
                journal_path=journal, version=_version(),
            )

    for name in registry.names():
        group.add_command(_make_command(registry.get(name)))
    group.add_command(_build_emu_group())
    group.add_command(_build_mcp_group())
    group.add_command(_build_tui_command())
    group.add_command(_build_web_command())
    return group


main = build_cli()

if __name__ == "__main__":
    main()
