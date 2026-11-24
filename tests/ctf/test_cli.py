# SPDX-License-Identifier: GPL-3.0-or-later
from click.testing import CliRunner

from carbon.cli import main


def _run(tmp_path, *args):
    p = tmp_path / "prog.json"
    return CliRunner().invoke(main, ["ctf", "--progress", str(p), *args])


def test_ctf_registered():
    assert "ctf" in main.commands


def test_list_shows_challenges_and_lock_state(tmp_path):
    r = _run(tmp_path, "list")
    assert r.exit_code == 0, r.output
    assert "recon-sec-service" in r.output
    assert "unlock-protected" in r.output
    assert "verrouillé" in r.output  # a gated challenge starts locked


def test_start_available_shows_briefing(tmp_path):
    r = _run(tmp_path, "start", "read-vin")
    assert r.exit_code == 0, r.output
    assert "VIN" in r.output


def test_start_locked_is_refused(tmp_path):
    r = _run(tmp_path, "start", "seed-key-algo")
    assert r.exit_code != 0
    assert "verrouillé" in r.output


def test_submit_correct_solves_and_unlocks(tmp_path):
    # recon + vin are the prerequisites of unlock-protected
    assert _run(tmp_path, "submit", "recon-sec-service", "CARBON{0x27}").exit_code == 0
    r = _run(tmp_path, "submit", "read-vin", "CARBON{CARBONSIMECU00001}")
    assert r.exit_code == 0, r.output
    assert "Correct" in r.output
    assert "unlock-protected" in r.output  # newly unlocked, both prereqs now solved


def test_submit_wrong_fails(tmp_path):
    r = _run(tmp_path, "submit", "recon-sec-service", "CARBON{nope}")
    assert r.exit_code == 1
    assert "incorrect" in r.output.lower()


def test_submit_locked_refused(tmp_path):
    r = _run(tmp_path, "submit", "seed-key-algo", "CARBON{a43cb70d}")
    assert r.exit_code != 0
    assert "verrouillé" in r.output


def test_hint_reveals_progressively(tmp_path):
    r1 = _run(tmp_path, "hint", "read-vin")
    assert "Indice 1/" in r1.output
    r2 = _run(tmp_path, "hint", "read-vin")
    assert "Indice 2/" in r2.output


def test_status_and_reset(tmp_path):
    _run(tmp_path, "submit", "recon-sec-service", "CARBON{0x27}")
    assert "1/" in _run(tmp_path, "status").output
    _run(tmp_path, "reset", "recon-sec-service")
    # after reset it is unsolved again
    assert "0/" in _run(tmp_path, "status").output


def test_unknown_challenge_errors_cleanly(tmp_path):
    r = _run(tmp_path, "start", "nope")
    assert r.exit_code != 0 and "inconnu" in r.output
