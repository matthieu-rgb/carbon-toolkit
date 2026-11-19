# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture CAN traffic to a file in candump -l log format.

Line format (compatible with can-utils candump -l / canplayer):

    (1700000000.000000) vcan0 123#DEADBEEF

Standard IDs are written as 3 hex digits, extended IDs as 8 hex digits.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from carbon.can.bus import open_bus, receive_frames
from carbon.core.adapter import Adapter
from carbon.core.result import ToolResult

_LINE = re.compile(
    r"^\((?P<ts>\d+(?:\.\d+)?)\)\s+(?P<chan>\S+)\s+"
    r"(?P<id>[0-9A-Fa-f]{3}|[0-9A-Fa-f]{8})#(?P<data>(?:[0-9A-Fa-f]{2})*)$"
)


def format_line(timestamp: float, channel: str, arb_id: int, data: bytes, extended: bool) -> str:
    id_s = f"{arb_id:08X}" if extended else f"{arb_id:03X}"
    return f"({timestamp:.6f}) {channel} {id_s}#{data.hex().upper()}"


def parse_capture(path: str) -> list[tuple[int, bytes, bool]]:
    """Parse a candump -l file into (arb_id, data, extended) tuples.

    Raises ValueError (naming the line number) on a corrupt line, or if the
    file holds no frame at all.
    """
    frames: list[tuple[int, bytes, bool]] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            m = _LINE.match(line)
            if m is None:
                raise ValueError(f"{path}: corrupt capture line {lineno}: {line!r}")
            id_s = m.group("id")
            extended = len(id_s) == 8
            arb_id = int(id_s, 16)
            data = bytes.fromhex(m.group("data"))
            if len(data) > 8:
                raise ValueError(f"{path}: line {lineno}: payload longer than 8 bytes")
            if arb_id > (0x1FFFFFFF if extended else 0x7FF):
                raise ValueError(f"{path}: line {lineno}: arbitration id out of range")
            frames.append((arb_id, data, extended))
    if not frames:
        raise ValueError(f"{path}: empty capture file (no frames)")
    return frames


class CanDump(Adapter):
    name = "can_dump"
    destructive = False

    def run(
        self,
        channel: str = "vcan0",
        interface: str = "socketcan",
        path: str = "capture.log",
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
        with open(path, "w", encoding="utf-8") as fh:
            for m in msgs:
                fh.write(
                    format_line(
                        m.timestamp, channel, m.arbitration_id, bytes(m.data), bool(m.is_extended_id)
                    )
                    + "\n"
                )
        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"Dumped {len(msgs)} frame(s) from {channel} to {path}",
            started_at=started,
            ended_at=datetime.now(timezone.utc),
            data={"frames": len(msgs)},
            artifacts=[str(path)],
        )
