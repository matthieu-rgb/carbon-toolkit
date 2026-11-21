# SPDX-License-Identifier: GPL-3.0-or-later
"""Replay a candump -l capture file onto a CAN bus (destructive)."""
from __future__ import annotations

from datetime import datetime, timezone

from carbon.can.bus import open_bus, send_frame
from carbon.core.adapter import Adapter
from carbon.core.result import ToolResult
from carbon.tools.can_dump import parse_capture


class CanReplay(Adapter):
    name = "can_replay"
    destructive = True

    def run(
        self,
        channel: str = "vcan0",
        interface: str = "socketcan",
        path: str = "capture.log",
        **_: object,
    ) -> ToolResult:
        started = datetime.now(timezone.utc)
        frames = parse_capture(path)  # validates everything before touching the bus
        bus = open_bus(channel, interface)
        try:
            for arb_id, data, extended in frames:
                send_frame(bus, arb_id, data, extended)
        finally:
            bus.shutdown()
        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"Replayed {len(frames)} frame(s) from {path} on {channel}",
            started_at=started,
            ended_at=datetime.now(timezone.utc),
            data={"frames": len(frames)},
        )
