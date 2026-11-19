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
