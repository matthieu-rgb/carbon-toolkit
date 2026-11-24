# SPDX-License-Identifier: GPL-3.0-or-later
"""Challenge model, loader, and deterministic flag validation.

A flag is validated by one of three matchers:
- ``exact``  — case/space-insensitive string equality;
- ``regex``  — full-match of a pattern (for values that vary per attempt);
- ``hash``   — sha256 of the normalized submission equals a stored digest, so a
  shipped challenge file never contains the answer in clear.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class CtfError(Exception):
    """Raised when a challenge file is malformed."""


@dataclass(frozen=True)
class Hint:
    text: str
    cost: int = 0


@dataclass(frozen=True)
class Challenge:
    id: str
    title: str
    category: str
    difficulty: str
    briefing: str
    flag_match: str                         # exact | regex | hash
    points: int = 0
    requires: tuple[str, ...] = ()
    target: dict[str, Any] = field(default_factory=dict)
    flag_value: str | None = None           # match=exact
    flag_pattern: str | None = None         # match=regex
    flag_sha256: str | None = None          # match=hash
    hints: tuple[Hint, ...] = ()


def normalize(text: str) -> str:
    """Canonical form for comparison: trimmed, inner spaces removed, lowercased."""
    return re.sub(r"\s+", "", (text or "")).lower()


def check_flag(challenge: Challenge, submitted: str) -> bool:
    """True iff ``submitted`` satisfies the challenge's flag matcher."""
    if challenge.flag_match == "regex":
        return bool(re.fullmatch(challenge.flag_pattern or "", (submitted or "").strip()))
    if challenge.flag_match == "hash":
        digest = hashlib.sha256(normalize(submitted).encode()).hexdigest()
        return bool(challenge.flag_sha256) and digest == challenge.flag_sha256.lower()
    return normalize(submitted) == normalize(challenge.flag_value or "")


def _challenge_from_dict(d: dict[str, Any]) -> Challenge:
    try:
        flag = d["flag"]
        match = flag["match"]
        if match not in ("exact", "regex", "hash"):
            raise CtfError(f"challenge {d.get('id')!r}: unknown flag match {match!r}")
        return Challenge(
            id=d["id"], title=d["title"], category=d["category"],
            difficulty=d["difficulty"], briefing=d["briefing"].strip(),
            flag_match=match, points=int(d.get("points", 0)),
            requires=tuple(d.get("requires", []) or ()),
            target=dict(d.get("target", {}) or {}),
            flag_value=flag.get("value"), flag_pattern=flag.get("pattern"),
            flag_sha256=flag.get("sha256"),
            hints=tuple(Hint(h["text"], int(h.get("cost", 0)))
                        for h in d.get("hints", []) or ()),
        )
    except (KeyError, TypeError) as exc:
        raise CtfError(f"malformed challenge {d.get('id', '?')!r}: {exc}") from exc


def load_challenges(path: Path) -> list[Challenge]:
    """Load and validate a YAML list of challenges (fail-fast on bad data)."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CtfError(f"cannot read challenges {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise CtfError(f"challenges file {path} must be a YAML list")
    challenges = [_challenge_from_dict(d) for d in raw]
    ids = [c.id for c in challenges]
    if len(ids) != len(set(ids)):
        raise CtfError("duplicate challenge id")
    known = set(ids)
    for c in challenges:
        for req in c.requires:
            if req not in known:
                raise CtfError(f"challenge {c.id!r} requires unknown {req!r}")
    return challenges
