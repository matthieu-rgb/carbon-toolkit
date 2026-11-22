# SPDX-License-Identifier: GPL-3.0-or-later
"""Pluggable seed-key framework for UDS SecurityAccess, with a documented example."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SeedKeyAlgorithm(Protocol):
    """Anything able to compute a SecurityAccess key from an ECU seed."""

    def key_from_seed(self, seed: bytes) -> bytes: ...


@dataclass(frozen=True)
class ExampleSeedKey:
    """Educational seed-key algorithm (NOT a real manufacturer algorithm).

    With ``n = len(seed) * 8`` bits and ``full = 2**n - 1``:

    1. ``x = int.from_bytes(seed, "big")``
    2. ``x ^= mask & full``
    3. ``x = ((x << rotate) | (x >> (n - rotate))) & full``  (left rotation on n bits)
    4. ``key = x.to_bytes(len(seed), "big")``

    The key is deterministic and has the same length as the seed.
    Reference vector: seed ``11223344`` -> key ``a43cb70d`` (defaults).
    """

    mask: int = 0xA5A5A5A5
    rotate: int = 3

    def key_from_seed(self, seed: bytes) -> bytes:
        n = len(seed) * 8
        full = 2**n - 1
        x = int.from_bytes(seed, "big") ^ (self.mask & full)
        x = ((x << self.rotate) | (x >> (n - self.rotate))) & full
        return x.to_bytes(len(seed), "big")
