# SPDX-License-Identifier: GPL-3.0-or-later
"""Inject a single forged CAN frame (destructive)."""
from __future__ import annotations

from datetime import datetime, timezone

from carbon.can.bus import open_bus, send_frame
from carbon.core.adapter import Adapter
from carbon.core.result import ToolResult


def _validate(arb_id: int, data: list[int] | bytes, extended: bool) -> bytes:
    max_id = 0x1FFFFFFF if extended else 0x7FF
    if not isinstance(arb_id, int) or isinstance(arb_id, bool) or not 0 <= arb_id <= max_id:
        raise ValueError(f"arbitration id {arb_id!r} out of range 0..{max_id:#x}")
    if len(data) > 8:
        raise ValueError(f"payload too long: {len(data)} bytes (max 8)")
    for b in data:
        if not isinstance(b, int) or isinstance(b, bool) or not 0 <= b <= 255:
            raise ValueError(f"invalid data byte {b!r}: must be 0..255")
    return bytes(data)


class CanInject(Adapter):
    name = "can_inject"
    destructive = True

    def run(
        self,
        channel: str = "vcan0",
        interface: str = "socketcan",
        arb_id: int = 0,
        data: list[int] | bytes = (),
        extended: bool = False,
        **_: object,
    ) -> ToolResult:
        started = datetime.now(timezone.utc)
        payload = _validate(arb_id, data, extended)
        bus = open_bus(channel, interface)
        try:
            send_frame(bus, arb_id, payload, extended)
        finally:
            bus.shutdown()
        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"Injected {arb_id:#x}#{payload.hex()} on {channel}",
            started_at=started,
            ended_at=datetime.now(timezone.utc),
            data={"arbitration_id": arb_id, "extended": extended, "data": payload.hex()},
        )
