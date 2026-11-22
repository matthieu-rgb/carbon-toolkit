# SPDX-License-Identifier: GPL-3.0-or-later
"""Clear stored DTCs (ClearDiagnosticInformation, 0x14). Destructive."""
from __future__ import annotations

from datetime import datetime, timezone

from udsoncan.exceptions import NegativeResponseException

from carbon.core.adapter import Adapter
from carbon.core.result import ToolResult
from carbon.uds.connection import open_uds_client, uds_errors


class UdsClearDtc(Adapter):
    name = "uds_clear_dtc"
    destructive = True

    def run(
        self,
        channel: str = "vcan0",
        interface: str = "socketcan",
        group: int = 0xFFFFFF,
        rxid: int = 0x7E8,
        txid: int = 0x7E0,
        **_: object,
    ) -> ToolResult:
        started = datetime.now(timezone.utc)
        with open_uds_client(channel, interface, rxid=rxid, txid=txid) as client:
            try:
                with uds_errors("clear dtc"):
                    client.clear_dtc(group)
            except NegativeResponseException as exc:
                code = exc.response.code
                return ToolResult(
                    tool=self.name,
                    ok=False,
                    summary=f"clear DTC rejected: NRC 0x{code:02x}",
                    started_at=started,
                    ended_at=datetime.now(timezone.utc),
                    data={"cleared": False, "group": f"0x{group:06x}", "nrc": f"0x{code:02x}"},
                )
        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"DTC group 0x{group:06x} cleared",
            started_at=started,
            ended_at=datetime.now(timezone.utc),
            data={"cleared": True, "group": f"0x{group:06x}"},
        )
