# SPDX-License-Identifier: GPL-3.0-or-later
"""Bundled challenge catalog and lock-state resolution."""
from __future__ import annotations

from pathlib import Path

from carbon.ctf.model import Challenge, load_challenges
from carbon.ctf.progress import Progress

_BUNDLED = Path(__file__).resolve().parent / "challenges" / "carbon_v1.yaml"

# status values
SOLVED = "solved"
AVAILABLE = "available"
LOCKED = "locked"


def bundled_challenges() -> list[Challenge]:
    """The challenges shipped with CARBON."""
    return load_challenges(_BUNDLED)


def status_of(challenge: Challenge, progress: Progress) -> str:
    """``solved`` if done, ``locked`` while any prerequisite is unsolved, else ``available``."""
    if progress.is_solved(challenge.id):
        return SOLVED
    solved = progress.solved_ids()
    if all(req in solved for req in challenge.requires):
        return AVAILABLE
    return LOCKED
