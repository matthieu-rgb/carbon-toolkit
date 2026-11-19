# SPDX-License-Identifier: GPL-3.0-or-later
"""Registry of available tool adapters."""
from __future__ import annotations

from carbon.core.adapter import Adapter


class Registry:
    def __init__(self) -> None:
        self._adapters: dict[str, Adapter] = {}

    def register(self, adapter: Adapter) -> None:
        if adapter.name in self._adapters:
            raise ValueError(f"adapter already registered: {adapter.name}")
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> Adapter:
        return self._adapters[name]

    def names(self) -> list[str]:
        return list(self._adapters)
