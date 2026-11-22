# SPDX-License-Identifier: GPL-3.0-or-later
"""Dataclasses describing a methodology attack tree."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Edge:
    to: str
    when: dict | None = None  # raw condition dict, not evaluated here


@dataclass
class Step:
    id: str
    title: str
    objective: str
    tool: str | None
    params: dict
    prompt_params: list[str]
    expected: str
    conditions: list[dict] = field(default_factory=list)
    next: list[Edge] = field(default_factory=list)


@dataclass
class Methodology:
    start: str
    steps: dict[str, Step]
