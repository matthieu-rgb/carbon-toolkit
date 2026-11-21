# SPDX-License-Identifier: GPL-3.0-or-later
from carbon.core.adapter import Adapter
from carbon.core.confirm import authorize
from carbon.core.result import ToolResult


def _adapter(destructive):
    class A(Adapter):
        name = "a"

        def run(self, **params) -> ToolResult:  # pragma: no cover
            raise NotImplementedError

    A.destructive = destructive
    return A()


def _boom(*_a, **_k):
    raise AssertionError("prompt_fn must not be called")


def test_non_destructive_always_true():
    assert authorize(_adapter(False), assume_yes=False, interactive=False, prompt_fn=_boom) is True


def test_destructive_assume_yes_true():
    assert authorize(_adapter(True), assume_yes=True, interactive=False, prompt_fn=_boom) is True


def test_destructive_interactive_prompts():
    a = _adapter(True)
    assert authorize(a, assume_yes=False, interactive=True, prompt_fn=lambda _p: "y") is True
    assert authorize(a, assume_yes=False, interactive=True, prompt_fn=lambda _p: "n") is False


def test_destructive_noninteractive_no_yes_returns_false_without_prompting():
    assert authorize(_adapter(True), assume_yes=False, interactive=False, prompt_fn=_boom) is False
