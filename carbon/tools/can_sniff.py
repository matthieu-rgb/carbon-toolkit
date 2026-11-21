# SPDX-License-Identifier: GPL-3.0-or-later
"""Passive CAN sniffer: collect frames from a bus."""
from __future__ import annotations

from datetime import datetime, timezone

from carbon.can.bus import open_bus, receive_frames
from carbon.core.adapter import Adapter
from carbon.core.result import ToolResult


class CanSniff(Adapter):
    name = "can_sniff"
    destructive = False

    def run(
        self,
        channel: str = "vcan0",
        interface: str = "socketcan",
        count: int | None = None,
        timeout: float = 1.0,
        **_: object,
    ) -> ToolResult:
        started = datetime.now(timezone.utc)
        bus = open_bus(channel, interface)
        try:
            msgs = receive_frames(bus, count=count, timeout=timeout)
        finally:
            bus.shutdown()
        frames = [
            {
                "timestamp": m.timestamp,
                "arbitration_id": m.arbitration_id,
                "extended": bool(m.is_extended_id),
                "data": bytes(m.data).hex(),
            }
            for m in msgs
        ]
        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"Captured {len(frames)} frame(s) on {channel}",
            started_at=started,
            ended_at=datetime.now(timezone.utc),
            data={"frames": frames},
        )
