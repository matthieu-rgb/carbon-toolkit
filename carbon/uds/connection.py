# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared UDS (ISO 14229) client connection layer over isotp + udsoncan."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import can
import isotp
import udsoncan
import udsoncan.configs
from udsoncan.client import Client
from udsoncan.connections import PythonIsoTpConnection
from udsoncan.exceptions import NegativeResponseException, TimeoutException

from carbon.can.bus import BusError, open_bus


class UdsError(Exception):
    """Base class for CARBON UDS errors."""


class UdsTimeoutError(UdsError):
    """Raised when a UDS request gets no (timely) response."""


class UdsConnectionError(UdsError):
    """Raised when the UDS transport cannot be opened or fails."""


class _RawDidCodec(udsoncan.DidCodec):
    """Generic codec: any DID is read/written as raw bytes.

    Lets adapters call ReadDataByIdentifier on any DID without knowing its
    structure in advance. ``__len__`` raises ``ReadAllRemainingData`` so the
    whole response payload is consumed as-is.
    """

    def encode(self, val: bytes) -> bytes:
        return bytes(val)

    def decode(self, payload: bytes) -> bytes:
        return bytes(payload)

    def __len__(self) -> int:
        raise udsoncan.DidCodec.ReadAllRemainingData


@contextmanager
def open_uds_client(
    channel: str,
    interface: str = "socketcan",
    *,
    rxid: int = 0x7E8,
    txid: int = 0x7E0,
    timeout: float = 1.0,
) -> Iterator[Client]:
    """Yield a configured udsoncan Client over a pure-Python isotp stack.

    Opens the underlying python-can bus via :func:`carbon.can.bus.open_bus`,
    builds an ``isotp.CanStack`` (Normal 11-bit addressing, ``txid``/``rxid``)
    and a udsoncan ``Client`` with a generic raw DID codec and bounded
    timeouts. On exit the connection is closed and the bus is shut down.

    Transport/open failures are wrapped in :class:`UdsConnectionError`;
    ``BusUnavailableError`` from ``open_bus`` (already a descriptive
    ``BusError``) is re-wrapped in :class:`UdsConnectionError` for a single
    error surface.
    """
    timeout_ms = max(1, int(timeout * 1000))
    try:
        bus = open_bus(channel, interface=interface)
    except BusError as exc:
        raise UdsConnectionError(f"Could not open UDS bus: {exc}") from exc
    except (can.CanError, OSError) as exc:
        raise UdsConnectionError(f"Could not open UDS bus: {exc}") from exc

    try:
        address = isotp.Address(
            isotp.AddressingMode.Normal_11bits, txid=txid, rxid=rxid
        )
        stack = isotp.CanStack(
            bus=bus,
            address=address,
            params={
                "rx_flowcontrol_timeout": timeout_ms,
                "rx_consecutive_frame_timeout": timeout_ms,
            },
        )
        connection = PythonIsoTpConnection(stack)
        config = dict(udsoncan.configs.default_client_config)
        config["exception_on_negative_response"] = True
        config["data_identifiers"] = {"default": _RawDidCodec()}
        config["request_timeout"] = timeout
        config["p2_timeout"] = timeout
        config["p2_star_timeout"] = timeout
    except (can.CanError, OSError, isotp.IsoTpError, ValueError) as exc:
        bus.shutdown()
        raise UdsConnectionError(f"Could not set up UDS transport: {exc}") from exc

    client = Client(connection, config=config)
    try:
        try:
            client.open()
        except (can.CanError, OSError, isotp.IsoTpError, TimeoutException) as exc:
            raise UdsConnectionError(f"Could not open UDS transport: {exc}") from exc
        yield client
    finally:
        try:
            client.close()
        finally:
            bus.shutdown()


@contextmanager
def uds_errors(context: str) -> Iterator[None]:
    """Map UDS transport/timeout failures to the CARBON UDS error hierarchy.

    ``TimeoutException`` becomes :class:`UdsTimeoutError`; isotp errors,
    ``can.CanError`` and ``OSError`` become :class:`UdsConnectionError`.
    ``NegativeResponseException`` is let through untouched so adapters can
    turn NRCs into informative results.
    """
    try:
        yield
    except NegativeResponseException:
        raise
    except TimeoutException as exc:
        raise UdsTimeoutError(f"UDS timeout during {context}: {exc}") from exc
    except isotp.IsoTpError as exc:
        raise UdsConnectionError(f"UDS transport error during {context}: {exc}") from exc
    except (can.CanError, OSError) as exc:
        raise UdsConnectionError(f"UDS transport error during {context}: {exc}") from exc
