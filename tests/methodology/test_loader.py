# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from carbon.methodology.loader import MethodologyError, load_methodology
from carbon.methodology.schema import Edge, Methodology, Step

TOOLS = {"scan", "read_did"}

VALID = """
start: a
steps:
  - id: a
    title: First
    objective: do scan
    tool: scan
    params: {bus: can0}
    prompt_params: [target]
    expected: ok
    conditions:
      - {op: exists, path: x}
    next:
      - to: b
        when: {op: exists, path: x}
      - to: b
  - id: b
    title: Info
    objective: read
    expected: done
"""


def test_valid_loads():
    m = load_methodology(VALID, known_tools=TOOLS)
    assert isinstance(m, Methodology)
    assert m.start == "a"
    a, b = m.steps["a"], m.steps["b"]
    assert isinstance(a, Step)
    assert a.tool == "scan" and a.params == {"bus": "can0"}
    assert a.prompt_params == ["target"]
    assert a.conditions == [{"op": "exists", "path": "x"}]
    assert a.next == [Edge("b", {"op": "exists", "path": "x"}), Edge("b", None)]
    assert b.tool is None and b.params == {} and b.prompt_params == []
    assert b.conditions == [] and b.next == []


def test_path_source(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(VALID)
    assert load_methodology(p, known_tools=TOOLS).start == "a"
    assert load_methodology(str(p), known_tools=TOOLS).start == "a"


def test_unknown_tool():
    with pytest.raises(MethodologyError, match="nope"):
        load_methodology(VALID.replace("tool: scan", "tool: nope"), known_tools=TOOLS)


def test_edge_to_missing():
    with pytest.raises(MethodologyError, match="zzz"):
        load_methodology(VALID.replace("to: b\n        when", "to: zzz\n        when"), known_tools=TOOLS)


def test_malformed_yaml():
    with pytest.raises(MethodologyError):
        load_methodology("start: [a\nsteps: {", known_tools=TOOLS)


@pytest.mark.parametrize("bad", ["start: nope", "steps: []", "- 1\n- 2", ""])
def test_bad_start_or_shape(bad):
    text = bad if bad.startswith(("-", "steps", "")) and "start" not in bad else VALID.replace("start: a", bad)
    with pytest.raises(MethodologyError):
        load_methodology(text, known_tools=TOOLS)


def test_missing_start():
    with pytest.raises(MethodologyError, match="start"):
        load_methodology(VALID.replace("start: a\n", ""), known_tools=TOOLS)


def test_missing_required_field():
    with pytest.raises(MethodologyError, match="objective"):
        load_methodology(VALID.replace("    objective: read\n", ""), known_tools=TOOLS)


def test_duplicate_id():
    with pytest.raises(MethodologyError, match="duplicate"):
        load_methodology(VALID.replace("id: b", "id: a"), known_tools=TOOLS)


def test_uses_safe_load():
    with pytest.raises(MethodologyError):
        load_methodology("start: !!python/object/apply:os.getcwd []\nsteps: []", known_tools=TOOLS)
