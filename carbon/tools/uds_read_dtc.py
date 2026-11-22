# SPDX-License-Identifier: GPL-3.0-or-later
"""Read DTCs by status mask (ReadDTCInformation 0x19 / sub 0x02)."""
from __future__ import annotations

from datetime import datetime, timezone

from udsoncan.exceptions import NegativeResponseException

from carbon.core.adapter import Adapter
from carbon.core.result import ToolResult
from carbon.uds.connection import open_uds_client, uds_errors


class UdsReadDtc(Adapter):
    name = "uds_read_dtc"
    destructive = False

    def run(
        self,
        channel: str = "vcan0",
        interface: str = "socketcan",
        status_mask: int = 0xFF,
        rxid: int = 0x7E8,
        txid: int = 0x7E0,
        **_: object,
    ) -> ToolResult:
        started = datetime.now(timezone.utc)
        with open_uds_client(channel, interface, rxid=rxid, txid=txid) as client:
            try:
                with uds_errors("read dtc"):
                    resp = client.get_dtc_by_status_mask(status_mask)
                    dtcs = [
                        {
                            "code": f"0x{d.id:06x}",
                            "status": f"0x{d.status.get_byte_as_int():02x}",
                        }
                        for d in resp.service_data.dtcs
                    ]
            except NegativeResponseException as exc:
                code = exc.response.code
                return ToolResult(
                    tool=self.name,
                    ok=False,
                    summary=f"read DTC rejected: NRC 0x{code:02x}",
                    started_at=started,
                    ended_at=datetime.now(timezone.utc),
                    data={"dtcs": [], "nrc": f"0x{code:02x}"},
                )
        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"{len(dtcs)} DTC(s) read",
            started_at=started,
            ended_at=datetime.now(timezone.utc),
            data={"dtcs": dtcs},
        )
