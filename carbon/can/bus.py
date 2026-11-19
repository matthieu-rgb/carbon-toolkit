# SPDX-License-Identifier: GPL-3.0-or-later
"""Thin wrapper over python-can: open a bus, send and receive frames."""
from __future__ import annotations

import time

import can


class BusError(Exception):
    """Base class for CARBON CAN bus errors."""


class BusUnavailableError(BusError):
    """Raised when the requested CAN interface/channel cannot be opened."""


class BusOperationError(BusError):
    """Raised when a send/receive on an open bus fails."""


def open_bus(channel: str, interface: str = "socketcan") -> can.BusABC:
    try:
        return can.Bus(channel=channel, interface=interface)
    except (can.CanError, OSError, ValueError, NotImplementedError) as exc:
        raise BusUnavailableError(
            f"CAN bus unavailable (interface={interface!r}, channel={channel!r}): {exc}. "
            "Check that the interface name is valid and the channel exists; "
            "on Linux run `sudo scripts/setup_vcan.sh` to create vcan0 "
            "(requires the `vcan` kernel module)."
        ) from exc


def send_frame(bus: can.BusABC, arb_id: int, data: bytes, extended: bool = False) -> None:
    try:
        bus.send(can.Message(arbitration_id=arb_id, data=data, is_extended_id=extended))
    except (can.CanError, OSError) as exc:
        raise BusOperationError(
            f"CAN send failed on channel {bus.channel_info!r} (id=0x{arb_id:x}): {exc}"
        ) from exc


def receive_frames(
    bus: can.BusABC, count: int | None = None, timeout: float = 1.0
) -> list[can.Message]:
    """Collect frames.

    count=None: read until `timeout` seconds pass with no new frame.
    count=N: return once N frames arrived or `timeout` elapsed in total.
    """
    try:
        return _receive(bus, count, timeout)
    except (can.CanError, OSError) as exc:
        raise BusOperationError(
            f"CAN receive failed on channel {bus.channel_info!r}: {exc}"
        ) from exc


def _receive(bus: can.BusABC, count: int | None, timeout: float) -> list[can.Message]:
    frames: list[can.Message] = []
    if count is None:
        while (msg := bus.recv(timeout=timeout)) is not None:
            frames.append(msg)
        return frames
    deadline = time.monotonic() + timeout
    while len(frames) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        msg = bus.recv(timeout=remaining)
        if msg is None:
            break
        frames.append(msg)
    return frames
