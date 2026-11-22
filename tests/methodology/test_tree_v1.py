# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from carbon.core.registry_builder import build_registry
from carbon.methodology.loader import load_methodology

TREE = Path(__file__).resolve().parents[2] / "carbon/methodology/trees/carbon_v1.yaml"
NAMES = set(build_registry().names())


def _load():
    return load_methodology(TREE, known_tools=NAMES)


def test_loads_and_validates_against_real_registry():
    assert _load().steps


def test_covers_all_six_phases():
    m = _load()
    tools = {s.tool for s in m.steps.values()}
    assert len(m.steps) >= 6
    assert None in tools  # access step
    assert {"can_sniff", "uds_scan", "uds_session", "uds_read_dtc",
            "uds_clear_dtc", "uds_security_access", "can_replay",
            "can_inject"} <= tools


def test_every_tool_is_real_and_destructive_present():
    m = _load()
    for s in m.steps.values():
        assert s.tool is None or s.tool in NAMES
    tools = {s.tool for s in m.steps.values()}
    assert {"uds_clear_dtc", "can_replay", "can_inject"} <= tools


def test_start_and_edges_resolve():
    m = _load()
    assert m.start in m.steps
    assert m.steps[m.start].tool is None
    for s in m.steps.values():
        for e in s.next:
            assert e.to in m.steps


def test_inject_prompts_for_arb_id_and_data():
    m = _load()
    inj = next(s for s in m.steps.values() if s.tool == "can_inject")
    assert {"arb_id", "data"} <= set(inj.prompt_params)


def test_edge_guards_reject_failed_results():
    """A negative response (ok=False) must NOT satisfy any forward edge guard,
    even when a data field is populated (regression: uds_session)."""
    from carbon.methodology.conditions import evaluate

    m = _load()
    # uds_session -> lire_dtc edge
    sess = next(s for s in m.steps.values() if s.tool == "uds_session")
    guard = sess.next[0].when
    ok_result = {"tool": "uds_session", "ok": True, "data": {"session": "extended"}}
    nrc_result = {"tool": "uds_session", "ok": False,
                  "data": {"session": "extended", "nrc": "0x7f"}}
    assert evaluate(guard, ok_result) is True
    assert evaluate(guard, nrc_result) is False

    # every forward edge guard conjoins ok:true -> all reject a failed result
    for s in m.steps.values():
        for e in s.next:
            if e.when is not None:
                assert evaluate(e.when, {"ok": False, "data": {}}) is False
