# SPDX-License-Identifier: GPL-3.0-or-later
import json
from datetime import datetime, timezone

import pytest

from carbon.core.journal import Journal, JournalError
from carbon.core.result import ToolResult


def _res(tool="t", ok=True, summary="s"):
    now = datetime.now(timezone.utc)
    return ToolResult(tool=tool, ok=ok, summary=summary, started_at=now, ended_at=now)


def test_record_appends_jsonl(tmp_path):
    p = tmp_path / "j.jsonl"
    j = Journal(p)
    j.record(_res("a"), {}, "op")
    j.record(_res("b"), {}, "op")
    lines = p.read_text().splitlines()
    assert [json.loads(line)["tool"] for line in lines] == ["a", "b"]


def test_record_includes_actor_and_params(tmp_path):
    p = tmp_path / "j.jsonl"
    Journal(p).record(_res(ok=False, summary="boom"), {"iface": "can0"}, "alice")
    e = json.loads(p.read_text())
    assert e["actor"] == "alice" and e["params"] == {"iface": "can0"}
    assert e["ok"] is False and e["summary"] == "boom" and e["ts"]
    datetime.fromisoformat(e["ts"])


def test_unwritable_path_raises_journal_error(tmp_path):
    with pytest.raises(JournalError):
        Journal(tmp_path).record(_res(), {}, "op")  # path is a directory
