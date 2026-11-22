# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the pluggable seed-key framework and the example algorithm."""
from __future__ import annotations

from carbon.uds.seedkey import ExampleSeedKey


def test_example_key_is_deterministic_and_same_length():
    algo = ExampleSeedKey()
    seed = b"\x11\x22\x33\x44"
    key = algo.key_from_seed(seed)
    assert isinstance(key, bytes) and len(key) == 4
    assert algo.key_from_seed(seed) == key  # deterministic


def test_example_key_matches_reference_vector():
    # x = 0x11223344 ^ 0xA5A5A5A5 = 0xB48796E1 ; rotl32(0xB48796E1, 3) = 0xA43CB70D
    assert ExampleSeedKey().key_from_seed(b"\x11\x22\x33\x44") == bytes.fromhex("a43cb70d")


def test_different_seed_different_key():
    algo = ExampleSeedKey()
    assert algo.key_from_seed(b"\x00\x00\x00\x01") != algo.key_from_seed(b"\x00\x00\x00\x02")
