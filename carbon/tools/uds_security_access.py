# SPDX-License-Identifier: GPL-3.0-or-later
"""Unlock the ECU with the SecurityAccess (0x27) seed-key flow.

Runs in one connection: extended session, requestSeed, key computation with
the example algorithm, sendKey. The ECU keeps its state after we disconnect,
so on success it is left extended and unlocked for later commands.
"""
from __future__ import annotations

from datetime import datetime, timezone

from udsoncan.exceptions import NegativeResponseException

from carbon.core.adapter import Adapter
from carbon.core.result import ToolResult
from carbon.uds.connection import open_uds_client, uds_errors
from carbon.uds.seedkey import ExampleSeedKey

_SESSION_EXTENDED = 0x03


class UdsSecurityAccess(Adapter):
    name = "uds_security_access"
    destructive = False

    def run(
        self,
        channel: str = "vcan0",
        interface: str = "socketcan",
        level: int = 1,
        rxid: int = 0x7E8,
        txid: int = 0x7E0,
        **_: object,
    ) -> ToolResult:
        started = datetime.now(timezone.utc)
        seed_hex = ""
        with open_uds_client(channel, interface, rxid=rxid, txid=txid) as client:
            try:
                with uds_errors("security access"):
                    client.change_session(_SESSION_EXTENDED)
                    # udsoncan maps an odd level to requestSeed and its even
                    # counterpart to sendKey, so level=1 -> sub 0x01 / 0x02.
                    seed = client.request_seed(level).service_data.seed
                    seed_hex = seed.hex()
                    client.send_key(level, ExampleSeedKey().key_from_seed(seed))
            except NegativeResponseException as exc:
                code = exc.response.code
                return ToolResult(
                    tool=self.name,
                    ok=False,
                    summary=f"security access rejected: NRC 0x{code:02x}",
                    started_at=started,
                    ended_at=datetime.now(timezone.utc),
                    data={"unlocked": False, "seed": seed_hex, "level": level, "nrc": f"0x{code:02x}"},
                )
        return ToolResult(
            tool=self.name,
            ok=True,
            summary=f"security level {level} unlocked",
            started_at=started,
            ended_at=datetime.now(timezone.utc),
            data={"unlocked": True, "seed": seed_hex, "level": level},
        )
