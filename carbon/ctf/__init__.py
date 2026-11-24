# SPDX-License-Identifier: GPL-3.0-or-later
"""CARBON CTF: declarative challenges played against the simulated ECU.

Challenges describe a goal and a flag; the player reaches the flag using CARBON's
own tools (uds_scan, uds_session, uds_security_access, …). The runner validates
a submitted flag deterministically and tracks progress locally — no server, no
new execution path, challenge logic stays in the simulated ECU.
"""
from carbon.ctf.model import Challenge, Hint, check_flag, load_challenges, normalize
from carbon.ctf.progress import Progress, load_progress
from carbon.ctf.catalog import bundled_challenges, status_of

__all__ = [
    "Challenge", "Hint", "check_flag", "load_challenges", "normalize",
    "Progress", "load_progress", "bundled_challenges", "status_of",
]
