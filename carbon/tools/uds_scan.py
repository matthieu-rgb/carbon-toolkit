# SPDX-License-Identifier: GPL-3.0-or-later
"""Enumerate the UDS services (SIDs) an ECU supports.

Each SID is probed once with a harmless request and classified:

* supported   - positive response, or any NRC other than 0x11
                (an NRC proves the service exists, e.g. 0x7F, 0x12, 0x13)
* unsupported - NRC 0x11 (serviceNotSupported)

Probes never perform a state-changing action. Where the natural request would
be destructive (0x14 ClearDiagnosticInformation, 0x11 ECUReset, writes, ...),
the probe is the bare SID with no parameters: an ECU that implements the
service rejects it with NRC 0x13 (incorrectMessageLength) before acting.

The same rule applies to otherwise-benign services whose documented request
would mutate state: 0x10 DiagnosticSessionControl is probed with the bare SID
(no sub-function) rather than ``0x10 0x01``, because switching to the default
session would re-lock SecurityAccess and silently undo a prior unlock. The
bare SID still proves the service exists (it answers with an NRC other than
0x11) without changing the active session.
"""
from __future__ import annotations

from datetime import datetime, timezone

from carbon.core.adapter import Adapter
from carbon.core.result import ToolResult
from carbon.uds.connection import open_uds_client, uds_errors

_NRC_SERVICE_NOT_SUPPORTED = 0x11

# Harmless real requests for read-only / benign services.
_PROBES: dict[int, bytes] = {
    0x10: b"\x10",  # DiagnosticSessionControl: bare SID (no session switch)
    0x19: b"\x19\x02\xff",  # ReadDTCInformation: by status mask (read-only)
    0x22: b"\x22\xf1\x90",  # ReadDataByIdentifier: VIN (read-only)
    0x3E: b"\x3e\x00",  # TesterPresent
}

# Services whose real use changes state: probed with the bare SID (invalid
# length -> NRC 0x13 if present; never executed). 0x14 must never clear DTCs.
_SID_ONLY = (0x11, 0x14, 0x27, 0x28, 0x2E, 0x2F, 0x31, 0x34, 0x85)

DEFAULT_SIDS: tuple[int, ...] = tuple(sorted({*_PROBES, *_SID_ONLY}))


class UdsScan(Adapter):
    name = "uds_scan"
    destructive = False

    def run(
        self,
        channel: str = "vcan0",
        interface: str = "socketcan",
        rxid: int = 0x7E8,
        txid: int = 0x7E0,
        **_: object,
    ) -> ToolResult:
        started = datetime.now(timezone.utc)
        supported: list[str] = []
        unsupported: list[str] = []
        with open_uds_client(channel, interface, rxid=rxid, txid=txid) as client:
            for sid in DEFAULT_SIDS:
                probe = _PROBES.get(sid, bytes([sid]))
                if self._is_supported(client, probe):
                    supported.append(f"0x{sid:02x}")
                else:
                    unsupported.append(f"0x{sid:02x}")
        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"{len(supported)} of {len(DEFAULT_SIDS)} probed services supported",
            started_at=started,
            ended_at=datetime.now(timezone.utc),
            data={"supported": supported, "unsupported": unsupported},
        )

    @staticmethod
    def _is_supported(client, probe: bytes) -> bool:
        """Send a raw request; only NRC 0x11 means unsupported.

        Transport/timeout failures propagate as UdsError.
        """
        conn = client.conn
        with uds_errors(f"probe of SID 0x{probe[0]:02x}"):
            conn.empty_rxqueue()
            conn.send(probe)
            response = conn.wait_frame(timeout=client.config["request_timeout"], exception=True)
        if response and response[0] == 0x7F and len(response) >= 3 and response[2] == _NRC_SERVICE_NOT_SUPPORTED:
            return False
        return True
