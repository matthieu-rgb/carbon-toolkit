# SPDX-License-Identifier: GPL-3.0-or-later
"""Proof of the pinned Textual headless API (run_test / Pilot)."""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Label


class _Mini(App):
    BINDINGS = [("x", "mark", "mark")]

    def __init__(self) -> None:
        super().__init__()
        self.marked = False

    def compose(self) -> ComposeResult:
        yield Label("hello", id="l")

    def action_mark(self) -> None:
        self.marked = True


def test_run_test_mounts_and_handles_key():
    async def body():
        app = _Mini()
        async with app.run_test() as pilot:
            assert app.query_one("#l", Label) is not None
            await pilot.press("x")
            await pilot.pause()
            assert app.marked
    asyncio.run(body())
