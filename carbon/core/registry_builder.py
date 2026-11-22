# SPDX-License-Identifier: GPL-3.0-or-later
"""Single place where tool adapters are registered."""
from __future__ import annotations

from carbon.core.registry import Registry
from carbon.tools.can_dump import CanDump
from carbon.tools.can_inject import CanInject
from carbon.tools.can_replay import CanReplay
from carbon.tools.can_sniff import CanSniff
from carbon.tools.uds_clear_dtc import UdsClearDtc
from carbon.tools.uds_read_did import UdsReadDid
from carbon.tools.uds_read_dtc import UdsReadDtc
from carbon.tools.uds_scan import UdsScan
from carbon.tools.uds_security_access import UdsSecurityAccess
from carbon.tools.uds_session import UdsSession


def build_registry() -> Registry:
    """Single place where adapters are registered."""
    registry = Registry()
    for adapter in (
        CanSniff(), CanDump(), CanReplay(), CanInject(),
        UdsScan(), UdsSession(), UdsSecurityAccess(),
        UdsReadDid(), UdsReadDtc(), UdsClearDtc(),
    ):
        registry.register(adapter)
    return registry
