# SPDX-License-Identifier: GPL-3.0-or-later
"""Read a data identifier (ReadDataByIdentifier, 0x22)."""
from __future__ import annotations

from datetime import datetime, timezone

from udsoncan.exceptions import NegativeResponseException

from carbon.core.adapter import Adapter
from carbon.core.result import ToolResult
from carbon.uds.connection import open_uds_client, uds_errors


class UdsReadDid(Adapter):
    name = "uds_read_did"
    destructive = False

    def run(
        self,
        channel: str = "vcan0",
        interface: str = "socketcan",
        did: int = 0xF190,
        rxid: int = 0x7E8,
        txid: int = 0x7E0,
        **_: object,
    ) -> ToolResult:
        started = datetime.now(timezone.utc)
        with open_uds_client(channel, interface, rxid=rxid, txid=txid) as client:
            try:
                with uds_errors("read did"):
                    value = client.read_data_by_identifier(did).service_data.values[did]
            except NegativeResponseException as exc:
                code = exc.response.code
                return ToolResult(
                    tool=self.name,
                    ok=False,
                    summary=f"read DID 0x{did:04x} rejected: NRC 0x{code:02x}",
                    started_at=started,
                    ended_at=datetime.now(timezone.utc),
                    data={"did": did, "nrc": f"0x{code:02x}"},
                )
        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"DID 0x{did:04x} = {bytes(value).hex()}",
            started_at=started,
            ended_at=datetime.now(timezone.utc),
            data={"did": did, "value": bytes(value).hex()},
        )
