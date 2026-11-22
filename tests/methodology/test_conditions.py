# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from carbon.methodology.conditions import _resolve, evaluate


def R(ok=True, **data):
    return {"tool": "t", "ok": ok, "summary": "", "data": data, "artifacts": []}


def test_ok():
    assert evaluate({"ok": True}, R(True))
    assert not evaluate({"ok": True}, R(False))
    assert evaluate({"ok": False}, R(False))


def test_equals():
    assert evaluate({"equals": ["data.cleared", True]}, R(cleared=True))
    assert not evaluate({"equals": ["data.cleared", True]}, R(cleared=False))


def test_contains_list_and_substring():
    r = R(supported=["0x10", "0x27"], text="seed=0x27ab")
    assert evaluate({"contains": ["data.supported", "0x27"]}, r)
    assert not evaluate({"contains": ["data.supported", "0x99"]}, r)
    assert evaluate({"contains": ["data.text", "0x27"]}, r)
    assert not evaluate({"contains": ["data.text", "zz"]}, r)


def test_exists_truthy():
    r = R(a=1, b=0)
    assert evaluate({"exists": "data.b"}, r)
    assert not evaluate({"exists": "data.zz"}, r)
    assert evaluate({"truthy": "data.a"}, r)
    assert not evaluate({"truthy": "data.b"}, r)
    assert evaluate({"exists": "ok"}, r)


def test_missing_key_false_no_raise():
    r = R()
    for c in ({"exists": "data.x"}, {"truthy": "data.x"},
              {"equals": ["data.x", 1]}, {"contains": ["data.x", 1]}):
        assert evaluate(c, r) is False


def test_all_any_nested():
    r = R(frames=3, cleared=True)
    c = {"all": [{"ok": True}, {"any": [{"equals": ["data.cleared", False]},
                                         {"truthy": "data.frames"}]}]}
    assert evaluate(c, r)
    assert not evaluate({"all": [{"ok": True}, {"exists": "data.no"}]}, r)
    assert not evaluate({"any": []}, r)


def test_frames_zero_vs_positive():
    assert not evaluate({"truthy": "data.frames"}, R(frames=0))
    assert evaluate({"truthy": "data.frames"}, R(frames=5))


def test_resolve():
    assert _resolve("ok", R(True)) == (True, True)
    assert _resolve("data.a", R(a=2)) == (True, 2)
    assert _resolve("data.a", R()) == (False, None)
    assert _resolve("data.a.b", R(a={"b": 1}))[0] is False


def test_unknown_key_raises():
    with pytest.raises(ValueError):
        evaluate({"bogus": 1}, R())
