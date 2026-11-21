# SPDX-License-Identifier: GPL-3.0-or-later
import json

from click.testing import CliRunner

from carbon.cli import main

CH = "carbon_cli_test"


def _base(journal):
    return ["--channel", CH, "--interface", "virtual", "--journal", str(journal)]


def test_sniff_command_runs_on_virtual(tmp_path):
    j = tmp_path / "j.jsonl"
    r = CliRunner().invoke(main, _base(j) + ["can_sniff", "--timeout", "0.1"])
    assert r.exit_code == 0, r.output
    assert "frame" in r.output.lower()
    assert j.exists()


def test_inject_noninteractive_without_yes_refuses(tmp_path):
    j = tmp_path / "j.jsonl"
    r = CliRunner().invoke(main, _base(j) + ["can_inject", "123", "deadbeef"])
    assert r.exit_code != 0
    assert not j.exists()
    assert "Injected" not in r.output


def test_inject_with_yes_executes_and_journals(tmp_path):
    j = tmp_path / "j.jsonl"
    r = CliRunner().invoke(main, ["--yes"] + _base(j) + ["can_inject", "123", "deadbeef"])
    assert r.exit_code == 0, r.output
    assert "Injected" in r.output
    entry = json.loads(j.read_text().splitlines()[-1])
    assert entry["tool"] == "can_inject" and entry["actor"] == "cli"


def test_unknown_tool_errors_cleanly(tmp_path):
    r = CliRunner().invoke(main, _base(tmp_path / "j.jsonl") + ["nope"])
    assert r.exit_code != 0
    assert "Traceback" not in r.output


def _failing_cli(tmp_path, exc):
    from carbon.cli import build_cli
    from carbon.core.registry import Registry

    class Boom:
        name = "can_inject"
        destructive = True

        def run(self, **kw):
            raise exc

    reg = Registry()
    reg.register(Boom())
    return build_cli(reg)


def test_failed_destructive_run_is_journaled_and_clean(tmp_path):
    from carbon.can.bus import BusOperationError

    j = tmp_path / "j.jsonl"
    cli = _failing_cli(tmp_path, BusOperationError("CAN send failed on channel 'x': down"))
    r = CliRunner().invoke(cli, ["--yes"] + _base(j) + ["can_inject", "123", "aa"])
    assert r.exit_code != 0
    assert "Traceback" not in r.output
    assert "send failed" in r.output
    entry = json.loads(j.read_text().splitlines()[-1])
    assert entry["tool"] == "can_inject" and entry["ok"] is False
    assert entry["actor"] == "cli" and "send failed" in entry["summary"]
    assert entry["params"]["arb_id"] == 0x123


def test_cli_registers_uds_commands():
    from carbon.cli import build_cli

    cli = build_cli()
    for name in (
        "uds_scan", "uds_session", "uds_security_access",
        "uds_read_did", "uds_read_dtc", "uds_clear_dtc", "emu",
    ):
        assert name in cli.commands
    assert "start" in cli.commands["emu"].commands


def test_cli_clear_dtc_refused_without_yes_non_interactive(tmp_path):
    j = tmp_path / "j.jsonl"
    r = CliRunner().invoke(main, _base(j) + ["uds_clear_dtc"])
    assert r.exit_code != 0
    assert not j.exists()


def test_cli_read_vin_end_to_end(tmp_path):
    from carbon.emu.ecu import SimulatedEcu

    j = tmp_path / "j.jsonl"
    with SimulatedEcu("carbon-cli-e2e", interface="virtual"):
        r = CliRunner().invoke(
            main,
            ["--channel", "carbon-cli-e2e", "--interface", "virtual",
             "--journal", str(j), "uds_read_did", "F190"],
        )
    assert r.exit_code == 0, r.output
    assert b"CARBONSIMECU00001".hex() in r.output
    entry = json.loads(j.read_text().splitlines()[-1])
    assert entry["tool"] == "uds_read_did" and entry["ok"] is True


def test_cli_uds_timeout_is_journaled_and_clean(tmp_path):
    # No ECU on this channel: the UDS timeout must not surface as a traceback.
    j = tmp_path / "j.jsonl"
    r = CliRunner().invoke(
        main,
        ["--channel", "carbon-cli-noecu", "--interface", "virtual",
         "--journal", str(j), "uds_read_did"],
    )
    assert r.exit_code != 0
    assert "Traceback" not in r.output
    assert json.loads(j.read_text().splitlines()[-1])["ok"] is False
