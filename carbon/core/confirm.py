# SPDX-License-Identifier: GPL-3.0-or-later
"""Authorization gate for destructive actions (CAN injection, replay)."""
from __future__ import annotations

from carbon.core.adapter import Adapter


def authorize(adapter: Adapter, *, assume_yes: bool, interactive: bool, prompt_fn=input) -> bool:
    """Return True if the adapter may run.

    Non-destructive adapters always pass. Destructive ones need --yes or an
    interactive confirmation; otherwise refuse without ever reading stdin.
    """
    if not adapter.destructive:
        return True
    if assume_yes:
        return True
    if not interactive:
        return False
    answer = prompt_fn(f"{adapter.name} is destructive. Proceed? [y/N] ")
    return str(answer).strip().lower() in ("y", "yes")
