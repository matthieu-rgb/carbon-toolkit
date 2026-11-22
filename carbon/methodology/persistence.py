# SPDX-License-Identifier: GPL-3.0-or-later
"""Atomic JSON persistence of the methodology engine state.

Resume restores POSITION (current step, mode, history, pending choice) only.
It never touches the target: live state such as an ECU unlock is not and
cannot be restored; re-running the step re-establishes prerequisites.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Callable

from carbon.methodology.engine import Engine
from carbon.methodology.schema import Methodology


class StateError(Exception):
    """Raised by load_state for a missing, malformed or incomplete state file."""


def save_state(path: Path, *, methodology_ref: str, engine: Engine) -> None:
    """Write state atomically: temp file in the same dir, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"methodology_ref": methodology_ref, "engine": engine.to_dict()}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_state(path: Path, *,
               resolve_methodology: Callable[[str], Methodology]
               ) -> tuple[str, Engine]:
    """Load (methodology_ref, engine). Raises StateError if the file is
    missing, not valid JSON, or lacks the expected keys."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise StateError(f"state file not found: {path}") from None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StateError(f"malformed state file {path}: {exc}") from exc
    try:
        ref = doc["methodology_ref"]
        edict = doc["engine"]
    except (KeyError, TypeError) as exc:
        raise StateError(f"invalid state file {path}: missing {exc}") from exc
    return ref, Engine.from_dict(edict, resolve_methodology(ref))
