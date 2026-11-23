# SPDX-License-Identifier: GPL-3.0-or-later
import json

from carbon.cli_render import (
    make_console,
    read_journal,
    render_dashboard,
    render_result,
    suggest_next,
)
from carbon.core.result import ToolResult


def _h(tool, ok=True):
    return {"tool": tool, "ok": ok}


def test_suggest_next_empty_starts_with_scan():
    cmd, why = suggest_next([])
    assert cmd == "carbon uds_scan"
    assert why


def test_suggest_next_advances_with_progress():
    assert suggest_next([_h("uds_scan")])[0] == "carbon uds_session"
    assert suggest_next([_h("uds_scan"), _h("uds_session")])[0] == "carbon uds_security_access"
    seq = [_h("uds_scan"), _h("uds_session"), _h("uds_security_access")]
    assert suggest_next(seq)[0] == "carbon uds_read_dtc"


def test_suggest_next_ignores_failed_runs():
    # A failed uds_scan must not count as done.
    assert suggest_next([_h("uds_scan", ok=False)])[0] == "carbon uds_scan"


def test_suggest_next_all_done_points_to_clear():
    seq = [_h(t) for t in ("uds_scan", "uds_session", "uds_security_access", "uds_read_dtc")]
    assert suggest_next(seq)[0] == "carbon uds_clear_dtc --yes"


def test_read_journal_skips_missing_and_garbled(tmp_path):
    assert read_journal(tmp_path / "nope.jsonl") == []
    p = tmp_path / "j.jsonl"
    p.write_text(
        json.dumps({"tool": "uds_scan", "ok": True}) + "\n"
        + "not json\n"
        + "\n"
        + json.dumps({"tool": "uds_session", "ok": True}) + "\n",
        encoding="utf-8",
    )
    entries = read_journal(p)
    assert [e["tool"] for e in entries] == ["uds_scan", "uds_session"]


def _result(tool="uds_scan", ok=True, summary="6 services répondent"):
    from datetime import datetime, timezone

    start = datetime(2026, 11, 23, 19, 56, 49, 312237, tzinfo=timezone.utc)
    end = datetime(2026, 11, 23, 19, 56, 49, 379760, tzinfo=timezone.utc)
    return ToolResult(
        tool=tool, ok=ok, summary=summary,
        started_at=start, ended_at=end, data={}, artifacts=[],
    )


def test_render_result_shows_summary_and_next(capsys):
    console = make_console()  # recording console
    console.record = True
    render_result(console, _result(), [{"tool": "uds_scan", "ok": True}])
    out = console.export_text()
    assert "uds_scan" in out
    assert "6 services répondent" in out
    assert "carbon uds_session" in out  # the suggested next step


def test_render_result_failure_marks_and_suggests_retry():
    console = make_console()
    console.record = True
    render_result(console, _result(ok=False, summary="verrouillé (NRC 0x33)"),
                  [{"tool": "uds_scan", "ok": True}, {"tool": "uds_session", "ok": False}])
    out = console.export_text()
    assert "verrouillé" in out
    assert "carbon uds_session" in out  # session not ok yet -> suggested again


def test_render_dashboard_empty_shows_quickstart(tmp_path):
    console = make_console()
    console.record = True
    render_dashboard(console, channel="vcan0", interface="socketcan",
                     journal_path=tmp_path / "none.jsonl", version="0.6.0")
    out = console.export_text()
    assert "CARBON" in out
    assert "carbon emu start" in out
    assert "carbon uds_scan" in out


def test_render_dashboard_with_history_lists_actions_and_next(tmp_path):
    p = tmp_path / "j.jsonl"
    p.write_text(
        json.dumps({"ts": "2026-11-23T19:56:49+00:00", "tool": "uds_scan", "ok": True,
                    "summary": "6 services répondent"}) + "\n"
        + json.dumps({"ts": "2026-11-23T19:56:50+00:00", "tool": "uds_session", "ok": True,
                      "summary": "session étendue"}) + "\n",
        encoding="utf-8",
    )
    console = make_console()
    console.record = True
    render_dashboard(console, channel="vcan0", interface="socketcan",
                     journal_path=p, version="0.6.0")
    out = console.export_text()
    assert "uds_scan" in out and "uds_session" in out
    assert "carbon uds_security_access" in out  # next step after scan+session
