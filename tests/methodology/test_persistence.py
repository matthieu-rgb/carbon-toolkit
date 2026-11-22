# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from pathlib import Path
import os

import pytest

from carbon.methodology import persistence
from carbon.methodology.engine import Engine
from carbon.methodology.persistence import StateError, load_state, save_state
from carbon.methodology.schema import Edge, Methodology, Step


def _s(id, tool=None, next=(), conditions=()):
    return Step(id=id, title=id, objective="", tool=tool, params={},
                prompt_params=[], expected="", conditions=list(conditions),
                next=list(next))


def _meth():
    steps = [
        _s("a", "scan", [Edge("b", {"truthy": "data.found"}),
                         Edge("c", {"truthy": "data.alt"})]),
        _s("b", "seed-key", [Edge("end")]),
        _s("c", "write"),
        _s("end"),
    ]
    return Methodology(start="a", steps={s.id: s for s in steps})


def test_round_trip(tmp_path):
    e = Engine(_meth(), mode="libre")
    e.observe("scan", {"ok": True, "data": {"found": 1, "alt": 1}})
    assert e.pending_choice == ["b", "c"]
    p = tmp_path / "s.json"
    save_state(p, methodology_ref="m1", engine=e)
    ref, e2 = load_state(p, resolve_methodology=lambda r: _meth())
    assert ref == "m1"
    assert e2.to_dict() == e.to_dict()
    assert e2.current_id == "a" and e2.mode == "libre"
    assert e2.pending_choice == ["b", "c"] and len(e2.history) == 1


def test_creates_parent_dir_and_no_temp_left(tmp_path):
    p = tmp_path / "sub" / "dir" / "s.json"
    save_state(p, methodology_ref="m", engine=Engine(_meth()))
    assert sorted(x.name for x in p.parent.iterdir()) == ["s.json"]
    assert json.loads(p.read_text())["methodology_ref"] == "m"


def test_atomic_write_uses_replace(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    calls = []
    real = os.replace

    def spy(src, dst):
        calls.append((src, dst))
        # at replace time the temp holds complete JSON; target not yet new
        assert json.loads(Path(src).read_text())["methodology_ref"] == "m"
        return real(src, dst)

    monkeypatch.setattr(persistence.os, "replace", spy)
    save_state(p, methodology_ref="m", engine=Engine(_meth()))
    assert len(calls) == 1
    assert os.fspath(calls[0][1]) == os.fspath(p)
    assert os.path.dirname(calls[0][0]) == os.path.dirname(os.fspath(p))
    assert calls[0][0] != os.fspath(p)


def test_failed_write_leaves_old_target_intact(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    save_state(p, methodology_ref="old", engine=Engine(_meth()))
    before = p.read_text()

    def boom(src, dst):
        raise OSError("disk died")

    monkeypatch.setattr(persistence.os, "replace", boom)
    with pytest.raises(OSError):
        save_state(p, methodology_ref="new", engine=Engine(_meth()))
    assert p.read_text() == before
    assert [x.name for x in tmp_path.iterdir()] == ["s.json"]  # temp cleaned


def test_missing_file_raises_state_error(tmp_path):
    with pytest.raises(StateError, match="not found"):
        load_state(tmp_path / "nope.json", resolve_methodology=lambda r: _meth())


def test_malformed_json_raises_state_error(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"methodology_ref": "m", "eng')
    with pytest.raises(StateError, match="malformed"):
        load_state(p, resolve_methodology=lambda r: _meth())


def test_missing_keys_raises_state_error(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"foo": 1}')
    with pytest.raises(StateError):
        load_state(p, resolve_methodology=lambda r: _meth())


def test_resume_restores_position_not_live_target_state(tmp_path):
    """Resume is a PURE state restore: position/mode/history only.

    load_state has no tool/bus/target access, so it cannot re-establish a live
    ECU unlock (e.g. a seed-key session). The engine comes back exactly at the
    saved step; re-running that step is what re-establishes prerequisites.
    """
    e = Engine(_meth())
    e.observe("scan", {"ok": True, "data": {"found": 1}})
    assert e.current_id == "b"  # the seed-key step
    p = tmp_path / "s.json"
    save_state(p, methodology_ref="m", engine=e)

    resolved = []

    def resolver(ref):
        resolved.append(ref)  # the ONLY collaborator load_state touches
        return _meth()

    _, e2 = load_state(p, resolve_methodology=resolver)
    assert resolved == ["m"]
    assert e2.current_id == "b" and e2.mode == "guided"
    assert e2.history == e.history
    assert e2.current().tool == "seed-key"
    # nothing was executed: no observation recorded for the restore itself
    assert len(e2.history) == len(e.history)
