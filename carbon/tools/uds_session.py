# SPDX-License-Identifier: GPL-3.0-or-later
"""Switch the ECU's diagnostic session (UDS service 0x10)."""
from __future__ import annotations

from datetime import datetime, timezone

from udsoncan.exceptions import NegativeResponseException

from carbon.core.adapter import Adapter
from carbon.core.result import ToolResult
from carbon.uds.connection import open_uds_client, uds_errors

_SESSIONS = {"default": 0x01, "extended": 0x03}


class UdsSession(Adapter):
    name = "uds_session"
    destructive = False

    def run(
        self,
        channel: str = "vcan0",
        interface: str = "socketcan",
        session: str = "extended",
        rxid: int = 0x7E8,
        txid: int = 0x7E0,
        **_: object,
    ) -> ToolResult:
        if session not in _SESSIONS:
            raise ValueError(f"session must be one of {sorted(_SESSIONS)}, got {session!r}")
        started = datetime.now(timezone.utc)
        ok, summary, data = True, f"switched to {session} session", {"session": session}
        with open_uds_client(channel, interface, rxid=rxid, txid=txid) as client:
            try:
                with uds_errors(f"session change to {session}"):
                    client.change_session(_SESSIONS[session])
            except NegativeResponseException as exc:
                code = exc.response.code
                ok, summary = False, f"ECU rejected {session} session: NRC 0x{code:02x}"
                data = {"session": session, "nrc": f"0x{code:02x}"}
        return ToolResult(
            tool=self.name, ok=ok, summary=summary,
            started_at=started, ended_at=datetime.now(timezone.utc), data=data,
        )
