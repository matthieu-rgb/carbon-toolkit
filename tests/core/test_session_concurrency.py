# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from carbon.core.adapter import Adapter
from carbon.core.execute import Origin
from carbon.core.result import ToolResult
from carbon.core.session import Session


class Slow(Adapter):
    name = "slow"
    destructive = False

    def __init__(self):
        self.spans = []

    def run(self, **params):
        t0 = time.monotonic()
        time.sleep(0.05)
        t1 = time.monotonic()
        self.spans.append((t0, t1))
        t = datetime.now(timezone.utc)
        return ToolResult(tool=self.name, ok=True, summary="ok", started_at=t,
                          ended_at=t, data={}, artifacts=[])


def test_run_tool_serializes(tmp_path):
    s = Session(channel="x", interface="virtual", journal_path=tmp_path / "j.jsonl")
    a = Slow()
    s.registry.register(a)
    ts = [threading.Thread(target=lambda: s.run_tool("slow", origin=Origin.WEB))
          for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(s.history) == 2 and len(a.spans) == 2
    first, second = sorted(a.spans)
    assert first[1] <= second[0]
