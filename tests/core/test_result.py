# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime, timezone

from carbon.core.result import ToolResult


def make() -> ToolResult:
    return ToolResult(
        tool="can-sniff",
        ok=True,
        summary="12 frames",
        data={"count": 12, "ids": [0x7DF, 0x7E8]},
        artifacts=["out/capture.pcap"],
        started_at=datetime(2026, 11, 19, 10, 0, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 11, 19, 10, 0, 5, tzinfo=timezone.utc),
    )


def test_roundtrip_serialization():
    r = make()
    assert ToolResult.from_dict(r.to_dict()) == r


def test_to_dict_dates_are_iso_strings():
    d = make().to_dict()
    assert isinstance(d["started_at"], str)
    assert isinstance(d["ended_at"], str)
    assert d["started_at"] == "2026-11-19T10:00:00+00:00"
