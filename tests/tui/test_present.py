# SPDX-License-Identifier: GPL-3.0-or-later
from carbon.tui.present import (
    PHASES,
    action_card,
    activity_rows,
    banner_for,
    car_art,
    ecu_info,
    hbar,
    interpret,
    journal_block,
    journal_entries,
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


def test_hbar_fill_proportional():
    assert hbar(0, 10, width=10) == "░" * 10
    assert hbar(10, 10, width=10) == "█" * 10
    half = hbar(5, 10, width=10)
    assert half.count("█") == 5 and len(half) == 10
    # value above max is clamped
    assert hbar(99, 10, width=8) == "█" * 8


def test_activity_rows_has_labels_bars_and_rates():
    out = activity_rows([("CAN rx", "green", 8, 8, "16 /s"),
                         ("inject", "yellow", 0, 8, "0 /s")])
    assert "CAN rx" in out and "inject" in out
    assert "16 /s" in out and "green" in out and "█" in out


def test_car_art_coloured_by_lock():
    assert "C A R B O N" in car_art(True) and "green" in car_art(True)
    assert "red" in car_art(False) and "green" not in car_art(False)


def test_ecu_info_reports_session_security_services():
    surface = {"session": {"active": "extended", "unlocked": True},
               "nodes": [{"type": "service", "label": "0x10"},
                         {"type": "service", "label": "0x27"}]}
    out = ecu_info(surface)
    assert "extended" in out and "deverrouille" in out and "services" in out and "2" in out
    assert "verrouille" in ecu_info({"session": {"unlocked": False}})


def _mstate(tool="uds_scan", title="3. Decouverte UDS", mode="guided", objective="decouvrir",
            candidates=None):
    return {"loaded": True, "mode": mode,
            "current": {"id": "uds_scan", "title": title, "tool": tool, "objective": objective},
            "candidates": candidates or [{"id": "uds_session", "title": "Session", "tool": "uds_session"}],
            "pending_choice": False, "satisfied": True}


def test_action_card_shows_tool_objective_and_next():
    out = action_card(_mstate())
    assert "uds_scan" in out            # which tool
    assert "decouvrir" in out           # the objective (beginner)
    assert "uds_session" in out         # what is next (how to progress)
    assert "ACCOMPAGNE" in out


def test_action_card_includes_interpreted_result():
    last = {"tool": "uds_scan", "ok": True, "summary": "s", "data": {"supported": ["0x27"]}}
    out = action_card(_mstate(), last)
    assert "resultat" in out and "0x27" in out


def test_action_card_libre_is_distinct():
    out = action_card(_mstate(mode="libre"))
    assert "LIBRE" in out and "uds_scan" in out


def test_journal_block_is_a_tree_for_multiline():
    block = journal_block("10:00:00", ["seed-key", "cle calculee", "deverrouille"], ok=True)
    lines = block.splitlines()
    assert len(lines) == 3
    assert "10:00:00" in lines[0]
    assert "|" in lines[1] and "`" in lines[2]  # tree connectors
    # single-line entry stays one line
    assert len(journal_block("10:00:00", ["6 services"], ok=True).splitlines()) == 1


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
