# SPDX-License-Identifier: GPL-3.0-or-later
"""Load and fail-fast validate a methodology YAML document."""
from __future__ import annotations

from pathlib import Path

import yaml

from carbon.methodology.schema import Edge, Methodology, Step


class MethodologyError(Exception):
    """Authoring error in a methodology document."""


def _read(source: str | Path) -> str:
    """A Path, or a str naming an existing file, is read; any other str is YAML text."""
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    if "\n" not in source and len(source) < 4096:
        try:
            p = Path(source)
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except OSError:
            pass
    return source


def _req(d: dict, key: str, typ: type, where: str):
    if key not in d:
        raise MethodologyError(f"{where}: missing required field '{key}'")
    if not isinstance(d[key], typ):
        raise MethodologyError(f"{where}: '{key}' must be {typ.__name__}")
    return d[key]


def _opt(d: dict, key: str, typ: type, default, where: str):
    v = d.get(key)
    if v is None:
        return default
    if not isinstance(v, typ):
        raise MethodologyError(f"{where}: '{key}' must be {typ.__name__}")
    return v


def load_methodology(source: str | Path, *, known_tools: set[str]) -> Methodology:
    try:
        doc = yaml.safe_load(_read(source))
    except yaml.YAMLError as e:
        raise MethodologyError(f"malformed YAML: {e}") from e
    if not isinstance(doc, dict):
        raise MethodologyError("top level must be a mapping with 'start' and 'steps'")
    start = _req(doc, "start", str, "methodology")
    raw_steps = _req(doc, "steps", list, "methodology")

    steps: dict[str, Step] = {}
    for i, rs in enumerate(raw_steps):
        if not isinstance(rs, dict):
            raise MethodologyError(f"steps[{i}] must be a mapping")
        sid = _req(rs, "id", str, f"steps[{i}]")
        where = f"step '{sid}'"
        if sid in steps:
            raise MethodologyError(f"duplicate step id '{sid}'")
        tool = rs.get("tool")
        if tool is not None and not isinstance(tool, str):
            raise MethodologyError(f"{where}: 'tool' must be a string or null")
        if tool is not None and tool not in known_tools:
            raise MethodologyError(f"{where}: unknown tool '{tool}'")
        edges = []
        for j, re_ in enumerate(_opt(rs, "next", list, [], where)):
            if not isinstance(re_, dict):
                raise MethodologyError(f"{where}: next[{j}] must be a mapping")
            when = re_.get("when")
            if when is not None and not isinstance(when, dict):
                raise MethodologyError(f"{where}: next[{j}].when must be a mapping")
            edges.append(Edge(_req(re_, "to", str, f"{where} next[{j}]"), when))
        conds = _opt(rs, "conditions", list, [], where)
        if not all(isinstance(c, dict) for c in conds):
            raise MethodologyError(f"{where}: 'conditions' entries must be mappings")
        steps[sid] = Step(
            id=sid,
            title=_req(rs, "title", str, where),
            objective=_req(rs, "objective", str, where),
            tool=tool,
            params=_opt(rs, "params", dict, {}, where),
            prompt_params=_opt(rs, "prompt_params", list, [], where),
            expected=_req(rs, "expected", str, where),
            conditions=conds,
            next=edges,
        )

    if start not in steps:
        raise MethodologyError(f"start '{start}' names no step")
    for s in steps.values():
        for e in s.next:
            if e.to not in steps:
                raise MethodologyError(f"step '{s.id}': next references missing step '{e.to}'")
    return Methodology(start=start, steps=steps)
