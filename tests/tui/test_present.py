# SPDX-License-Identifier: GPL-3.0-or-later
from carbon.tui.present import (
    PHASES,
    banner_for,
    device_box,
    interpret,
    journal_entries,
    phase_of,
    progress_rail,
    services_from_surface,
    sparkline,
)


def test_phase_of_reads_leading_digit():
    assert phase_of("1. Accès physique") == 1
    assert phase_of("3a. Découverte des services UDS") == 3
    assert phase_of("4b. Effacement des DTC") == 4
    assert phase_of("no number") is None


def test_progress_rail_marks_done_current_pending():
    rail = progress_rail("3a. Découverte des services UDS")
    # all six phase labels appear
    for _, label in PHASES:
        assert label in rail
    assert "◆ UDS" in rail                       # current phase highlighted
    assert "[green]●[/] [dim]Accès[/]" in rail   # earlier phase done (green bullet)
    assert "[dim]○ Inject[/]" in rail            # later phase pending


def _r(tool, ok=True, **data):
    return {"tool": tool, "ok": ok, "summary": "raw", "data": data}


def test_interpret_uds_scan_flags_seed_key_opportunity():
    msg = interpret(_r("uds_scan", supported=["0x10", "0x27", "0x22"]))
    assert "3 service" in msg
    assert "0x27" in msg and "seed-key" in msg


def test_interpret_security_access_locked_and_unlocked():
    assert "déverrouillé" in interpret(_r("uds_security_access", unlocked=True, level=1))
    assert "refusé" in interpret(_r("uds_security_access", ok=False, nrc="0x33"))


def test_interpret_read_did_locked_vs_value():
    assert interpret(_r("uds_read_did", did=0x1234, value="deadbeef")).endswith("deadbeef")
    assert "verrouillé" in interpret(_r("uds_read_did", ok=False, did=0x1234, nrc="0x33"))


def test_interpret_dtc_count_and_sniff():
    assert interpret(_r("uds_read_dtc", dtcs=["a", "b"])).startswith("2 DTC")
    assert "3 trame" in interpret(_r("can_sniff", frames=[1, 2, 3]))


def test_interpret_unknown_tool_falls_back_to_summary():
    assert interpret({"tool": "mystery", "ok": True, "summary": "whatever"}) == "whatever"


def test_banner_fires_on_security_unlock_only_when_ok():
    assert banner_for(_r("uds_security_access", unlocked=True, level=1)) is not None
    text, cls = banner_for(_r("uds_security_access", unlocked=True, level=1))
    assert "DÉVERROUILLÉE" in text and cls == "banner-ok"
    assert banner_for(_r("uds_security_access", ok=False, nrc="0x33")) is None


def test_banner_fires_on_clear_dtc_and_read_did():
    assert banner_for(_r("uds_clear_dtc"))[0].endswith("EFFACÉS")
    assert "LU" in banner_for(_r("uds_read_did", did=0xF190, value="abcd"))[0]


def test_banner_none_for_ordinary_tools():
    assert banner_for(_r("uds_scan", supported=["0x10"])) is None


def test_journal_entries_expand_seed_key_sequence():
    seq = journal_entries(_r("uds_security_access", unlocked=True, seed="11223344", level=1))
    assert len(seq) == 3
    assert "requestSeed" in seq[0] and "11223344" in seq[0]
    assert "sendKey" in seq[1]
    assert "déverrouillé" in seq[2]


def test_journal_entries_seed_key_refused():
    seq = journal_entries(_r("uds_security_access", ok=False, seed="11223344", nrc="0x33"))
    assert seq[-1].startswith("✗") and "0x33" in seq[-1]


def test_journal_entries_single_line_for_other_tools():
    assert journal_entries(_r("uds_scan", supported=["0x10", "0x27"])) == [
        interpret(_r("uds_scan", supported=["0x10", "0x27"]))
    ]


def test_sparkline_width_and_scaling():
    assert len(sparkline([], width=12)) == 12
    assert sparkline([0, 0, 0], width=3) == "▁▁▁"
    line = sparkline([0, 5, 10], width=3)
    assert len(line) == 3 and line[0] == "▁" and line[2] == "█"
    # right-aligned padding when fewer values than width
    assert sparkline([10], width=4).endswith("█") and sparkline([10], width=4)[0] == "▁"


def test_device_box_reflects_lock_state():
    locked = device_box(unlocked=False, session=None)
    assert "locked" in locked and "red" in locked
    unlocked = device_box(unlocked=True, session="extended")
    assert "unlocked" in unlocked and "green" in unlocked and "extended" in unlocked


def test_services_from_surface_lists_services_and_lock_state():
    surface = {"nodes": [
        {"type": "bus", "label": "vcan0"},
        {"type": "service", "label": "0x27"},
        {"type": "service", "label": "0x22"},
        {"type": "level", "state": "unlocked"},
    ]}
    rows = services_from_surface(surface)
    labels = [r["label"] for r in rows]
    assert "0x27" in labels and "sécurité" in labels
    sec = next(r for r in rows if r["label"] == "sécurité")
    assert sec["name"] == "déverrouillé"
    svc = next(r for r in rows if r["label"] == "0x27")
    assert svc["name"] == "sécurité"  # 0x27 -> security access
