# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from carbon.methodology.engine import Engine
from carbon.methodology.schema import Edge, Methodology, Step


def _s(id, tool=None, next=(), conditions=()):
    return Step(id=id, title=id, objective="", tool=tool, params={},
                prompt_params=[], expected="", conditions=list(conditions),
                next=list(next))


def _meth():
    steps = [
        _s("a", "scan", [
            Edge("b", {"truthy": "data.found"}),
            Edge("c", {"truthy": "data.alt"}),
            Edge("fix", {"all": [{"ok": False}, {"equals": ["data.nrc", 0x35]}]}),
        ], conditions=[{"ok": True}]),
        _s("b", "read", [Edge("end")]),
        _s("c", "write"),
        _s("fix", "seed-key", [Edge("a")]),
        _s("info", None, [Edge("end")]),
        _s("end"),
    ]
    return Methodology(start="a", steps={s.id: s for s in steps})


def test_current_and_candidates():
    e = Engine(_meth())
    assert e.current().id == "a"
    assert [s.id for s in e.candidates()] == ["b", "c", "fix"]


def test_single_match_advances():
    e = Engine(_meth())
    e.observe("scan", {"ok": True, "data": {"found": True}})
    assert e.current_id == "b" and e.pending_choice is None
    assert e.history[0]["tool"] == "scan" and e.history[0]["ok"] is True


def test_multi_match_pending_then_choose():
    e = Engine(_meth())
    e.observe("scan", {"ok": True, "data": {"found": 1, "alt": 1}})
    assert e.current_id == "a"
    assert e.pending_choice == ["b", "c"]
    e.choose("c")
    assert e.current_id == "c" and e.pending_choice is None


def test_zero_match_pending_all_candidates():
    e = Engine(_meth())
    e.observe("scan", {"ok": True, "data": {}})
    assert e.current_id == "a"
    assert e.pending_choice == ["b", "c", "fix"]


def test_choose_invalid():
    e = Engine(_meth())
    with pytest.raises(ValueError):
        e.choose("end")


def test_off_step_tool_no_advance():
    e = Engine(_meth())
    e.observe("read", {"ok": True, "data": {"found": True}})
    assert e.current_id == "a"
    assert e.history[-1]["off_step"] is True


def test_ack_no_tool_step():
    e = Engine(_meth())
    e.current_id = "info"
    e.ack()
    assert e.current_id == "end"


def test_ack_when_needs_data_not_matched():
    e = Engine(_meth())
    e.ack()  # step "a" has a tool; ack only applies to no-tool steps
    assert e.current_id == "a"
    m = _meth()
    m.steps["info"].next = [Edge("end", {"truthy": "data.x"})]
    e2 = Engine(m)
    e2.current_id = "info"
    e2.ack()
    assert e2.current_id == "info"


def test_allowed():
    e = Engine(_meth())
    assert e.allowed("scan") and e.allowed("read") and e.allowed("seed-key")
    assert not e.allowed("other")
    e.set_mode("libre")
    assert e.allowed("other")


def test_set_mode_roundtrip_keeps_pointer():
    e = Engine(_meth())
    e.observe("scan", {"ok": True, "data": {"found": True}})
    e.set_mode("libre")
    assert e.current_id == "b"
    e.set_mode("guided")
    assert e.current_id == "b" and e.mode == "guided"
    with pytest.raises(ValueError):
        e.set_mode("nope")
    with pytest.raises(ValueError):
        Engine(_meth(), mode="x")


def test_roundtrip():
    e = Engine(_meth())
    e.observe("scan", {"ok": True, "data": {"found": 1, "alt": 1}})
    e.set_mode("libre")
    e2 = Engine.from_dict(e.to_dict(), _meth())
    assert e2.to_dict() == e.to_dict()
    assert e2.pending_choice == ["b", "c"] and e2.mode == "libre"


def test_remediation_branch():
    e = Engine(_meth())
    e.observe("scan", {"ok": False, "data": {"nrc": 0x35}})
    assert e.current_id == "fix"
    assert e.position()["satisfied"] is None or isinstance(e.position(), dict)
