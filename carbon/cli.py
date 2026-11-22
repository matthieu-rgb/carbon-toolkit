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
from carbon.emu.ecu import EcuConfig, SimulatedEcu
from carbon.tools.can_dump import CanDump
from carbon.tools.can_inject import CanInject
from carbon.tools.can_replay import CanReplay
from carbon.tools.can_sniff import CanSniff
from carbon.tools.uds_clear_dtc import UdsClearDtc
from carbon.tools.uds_read_did import UdsReadDid
from carbon.tools.uds_read_dtc import UdsReadDtc
from carbon.tools.uds_scan import UdsScan
from carbon.tools.uds_security_access import UdsSecurityAccess
from carbon.tools.uds_session import UdsSession

DEFAULT_JOURNAL = "carbon-session.jsonl"  # relative to the current directory


def build_registry() -> Registry:
    """Single place where adapters are registered."""
    registry = Registry()
    for adapter in (
        CanSniff(), CanDump(), CanReplay(), CanInject(),
        UdsScan(), UdsSession(), UdsSecurityAccess(),
        UdsReadDid(), UdsReadDtc(), UdsClearDtc(),
    ):
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
    group.add_command(_build_emu_group())
    group.add_command(_build_mcp_group())
    return group


main = build_cli()

if __name__ == "__main__":
    main()
