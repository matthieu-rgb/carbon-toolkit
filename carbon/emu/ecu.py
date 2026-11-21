# SPDX-License-Identifier: GPL-3.0-or-later
"""A home-grown ISO-TP/UDS server: a simulated ECU for testing CARBON adapters."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import isotp

from carbon.can.bus import open_bus
from carbon.uds.seedkey import ExampleSeedKey, SeedKeyAlgorithm

# Session IDs
_SESSION_DEFAULT = 0x01
_SESSION_EXTENDED = 0x03

# Negative Response Codes (ISO 14229)
_NRC_SERVICE_NOT_SUPPORTED = 0x11
_NRC_SUBFUNCTION_NOT_SUPPORTED = 0x12
_NRC_REQUEST_SEQUENCE_ERROR = 0x24
_NRC_REQUEST_OUT_OF_RANGE = 0x31
_NRC_SECURITY_ACCESS_DENIED = 0x33
_NRC_INVALID_KEY = 0x35
_NRC_SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION = 0x7F

# Service IDs
_SID_SESSION = 0x10
_SID_CLEAR_DTC = 0x14
_SID_READ_DTC = 0x19
_SID_READ_DID = 0x22
_SID_SECURITY = 0x27
_SID_TESTER_PRESENT = 0x3E

_POSITIVE_OFFSET = 0x40
_SUPPRESS_POS_RSP_BIT = 0x80


@dataclass(frozen=True)
class EcuConfig:
    """Static identity and preloaded data for a :class:`SimulatedEcu`."""

    req_id: int = 0x7E0  # ECU receives here (client's txid)
    resp_id: int = 0x7E8  # ECU transmits here (client's rxid)
    seed: bytes = b"\x11\x22\x33\x44"
    vin: bytes = b"CARBONSIMECU00001"
    protected_did: int = 0x1234
    protected_value: bytes = b"\xDE\xAD\xBE\xEF"
    vin_did: int = 0xF190
    dtcs: list[tuple[int, int]] = field(
        default_factory=lambda: [(0x010203, 0x24), (0x040506, 0x2F)]
    )
    algo: SeedKeyAlgorithm = field(default_factory=ExampleSeedKey)


class SimulatedEcu:
    """ISO-TP/UDS responder with persistent session/security/DTC state.

    Parses raw UDS request PDUs at the byte level (full control over NRCs) and
    answers per the CARBON ECU contract. State (current session, lock status,
    issued seed, DTC store) lives on the instance and persists across client
    connections until a return to the default session or :meth:`stop`.
    """

    def __init__(
        self,
        channel: str,
        interface: str = "socketcan",
        config: EcuConfig | None = None,
    ) -> None:
        self.channel = channel
        self.interface = interface
        self.config = config or EcuConfig()
        self.ready = threading.Event()

        # Mutable, persistent ECU state.
        self._session = _SESSION_DEFAULT
        self._unlocked = False
        self._issued_seed: bytes | None = None
        self._dtcs: list[tuple[int, int]] = list(self.config.dtcs)

        self._bus = None
        self._stack: isotp.CanStack | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Open the bus, mount the isotp stack, and block until receiving."""
        if self._started:
            return
        self._bus = open_bus(self.channel, interface=self.interface)
        address = isotp.Address(
            isotp.AddressingMode.Normal_11bits,
            txid=self.config.resp_id,  # mirror: ECU transmits on resp_id
            rxid=self.config.req_id,  # ...and receives on req_id
        )
        self._stack = isotp.CanStack(
            bus=self._bus,
            address=address,
            params={
                "rx_flowcontrol_timeout": 1000,
                "rx_consecutive_frame_timeout": 1000,
            },
        )
        self._stack.start()  # internal rx/tx threads pump the CAN layer
        self._stop.clear()
        self.ready.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"SimulatedEcu[{self.channel}]", daemon=True
        )
        self._thread.start()
        if not self.ready.wait(timeout=5.0):
            self.stop()
            raise RuntimeError("SimulatedEcu listener failed to become ready")
        self._started = True

    def stop(self) -> None:
        """Stop the listener thread and shut the bus down. Idempotent."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._stack is not None:
            try:
                self._stack.stop()
            finally:
                self._stack = None
        if self._bus is not None:
            try:
                self._bus.shutdown()
            finally:
                self._bus = None
        self.ready.clear()
        self._started = False

    def __enter__(self) -> "SimulatedEcu":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- listener loop -----------------------------------------------------

    def _run(self) -> None:
        assert self._stack is not None
        self.ready.set()  # the stack is started; we are about to dequeue frames
        while not self._stop.is_set():
            request = self._stack.recv(block=True, timeout=0.2)
            if request is None:
                continue
            response = self._dispatch(bytes(request))
            if response is not None:
                self._stack.send(response)

    # -- UDS dispatch ------------------------------------------------------

    def _dispatch(self, request: bytes) -> bytes | None:
        if not request:
            return None
        sid = request[0]
        handler = {
            _SID_SESSION: self._handle_session,
            _SID_TESTER_PRESENT: self._handle_tester_present,
            _SID_SECURITY: self._handle_security,
            _SID_READ_DID: self._handle_read_did,
            _SID_READ_DTC: self._handle_read_dtc,
            _SID_CLEAR_DTC: self._handle_clear_dtc,
        }.get(sid)
        if handler is None:
            return self._negative(sid, _NRC_SERVICE_NOT_SUPPORTED)
        return handler(request)

    def _negative(self, sid: int, nrc: int) -> bytes:
        return bytes([0x7F, sid, nrc])

    @staticmethod
    def _subfunction(request: bytes) -> tuple[int, bool]:
        """Return (subfunction without suppress bit, suppress_positive)."""
        raw = request[1] if len(request) > 1 else 0x00
        return raw & ~_SUPPRESS_POS_RSP_BIT, bool(raw & _SUPPRESS_POS_RSP_BIT)

    def _positive(self, sid: int, payload: bytes, suppress: bool) -> bytes | None:
        if suppress:
            return None
        return bytes([sid + _POSITIVE_OFFSET]) + payload

    # -- service handlers --------------------------------------------------

    def _handle_session(self, request: bytes) -> bytes | None:
        sub, suppress = self._subfunction(request)
        if sub not in (_SESSION_DEFAULT, _SESSION_EXTENDED):
            return self._negative(_SID_SESSION, _NRC_SUBFUNCTION_NOT_SUPPORTED)
        self._session = sub
        if sub == _SESSION_DEFAULT:
            self._unlocked = False  # returning to default re-locks security
            self._issued_seed = None
        # P2 / P2* server timing record (values arbitrary; required since 2013).
        record = b"\x00\x32\x01\xF4"
        return self._positive(_SID_SESSION, bytes([sub]) + record, suppress)

    def _handle_tester_present(self, request: bytes) -> bytes | None:
        sub, suppress = self._subfunction(request)
        if sub != 0x00:
            return self._negative(_SID_TESTER_PRESENT, _NRC_SUBFUNCTION_NOT_SUPPORTED)
        return self._positive(_SID_TESTER_PRESENT, b"\x00", suppress)

    def _handle_security(self, request: bytes) -> bytes | None:
        sub, suppress = self._subfunction(request)
        if self._session != _SESSION_EXTENDED:
            return self._negative(
                _SID_SECURITY, _NRC_SERVICE_NOT_SUPPORTED_IN_ACTIVE_SESSION
            )
        if sub == 0x01:  # requestSeed
            self._issued_seed = self.config.seed
            return self._positive(
                _SID_SECURITY, bytes([sub]) + self.config.seed, suppress
            )
        if sub == 0x02:  # sendKey
            if self._issued_seed is None:
                return self._negative(_SID_SECURITY, _NRC_REQUEST_SEQUENCE_ERROR)
            expected = self.config.algo.key_from_seed(self._issued_seed)
            if request[2:] != expected:
                return self._negative(_SID_SECURITY, _NRC_INVALID_KEY)
            self._unlocked = True
            self._issued_seed = None
            return self._positive(_SID_SECURITY, bytes([sub]), suppress)
        return self._negative(_SID_SECURITY, _NRC_SUBFUNCTION_NOT_SUPPORTED)

    def _handle_read_did(self, request: bytes) -> bytes | None:
        if len(request) < 3:
            return self._negative(_SID_READ_DID, _NRC_REQUEST_OUT_OF_RANGE)
        did = int.from_bytes(request[1:3], "big")
        if did == self.config.vin_did:
            value = self.config.vin
        elif did == self.config.protected_did:
            if not self._unlocked:
                return self._negative(_SID_READ_DID, _NRC_SECURITY_ACCESS_DENIED)
            value = self.config.protected_value
        else:
            return self._negative(_SID_READ_DID, _NRC_REQUEST_OUT_OF_RANGE)
        return bytes([_SID_READ_DID + _POSITIVE_OFFSET]) + did.to_bytes(2, "big") + value

    def _handle_read_dtc(self, request: bytes) -> bytes | None:
        sub, suppress = self._subfunction(request)
        if sub != 0x02:  # reportDTCByStatusMask
            return self._negative(_SID_READ_DTC, _NRC_SUBFUNCTION_NOT_SUPPORTED)
        mask = request[2] if len(request) > 2 else 0x00
        status_availability_mask = 0xFF
        payload = bytes([sub, status_availability_mask])
        for code, status in self._dtcs:
            if status & mask:
                payload += code.to_bytes(3, "big") + bytes([status])
        return self._positive(_SID_READ_DTC, payload, suppress)

    def _handle_clear_dtc(self, request: bytes) -> bytes | None:
        if not self._unlocked:
            return self._negative(_SID_CLEAR_DTC, _NRC_SECURITY_ACCESS_DENIED)
        self._dtcs = []
        return bytes([_SID_CLEAR_DTC + _POSITIVE_OFFSET])
