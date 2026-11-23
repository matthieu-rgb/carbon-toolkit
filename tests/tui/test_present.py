# SPDX-License-Identifier: GPL-3.0-or-later
from carbon.tui.present import (
    PHASES,
    interpret,
    phase_of,
    progress_rail,
    services_from_surface,
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
