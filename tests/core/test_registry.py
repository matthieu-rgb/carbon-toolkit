# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime

import pytest

from carbon.core.adapter import Adapter
from carbon.core.registry import Registry
from carbon.core.result import ToolResult


NOW = datetime(2026, 1, 1)


class FakeAdapter(Adapter):
    def __init__(self, name: str = "fake") -> None:
        self.name = name

    def run(self, **params) -> ToolResult:
        return ToolResult(
            tool=self.name, ok=True, summary="ok",
            started_at=NOW, ended_at=NOW, data={}, artifacts=[],
        )


def test_register_and_get():
    reg = Registry()
    a = FakeAdapter("fake")
    reg.register(a)
    assert reg.get("fake") is a


def test_duplicate_name_raises():
    reg = Registry()
    reg.register(FakeAdapter("fake"))
    with pytest.raises(ValueError):
        reg.register(FakeAdapter("fake"))


def test_get_unknown_raises():
    with pytest.raises(KeyError):
        Registry().get("nope")


def test_names_lists_registered():
    reg = Registry()
    reg.register(FakeAdapter("a"))
    reg.register(FakeAdapter("b"))
    assert reg.names() == ["a", "b"]


def test_destructive_defaults_false():
    assert FakeAdapter().destructive is False
