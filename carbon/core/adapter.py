# SPDX-License-Identifier: GPL-3.0-or-later
"""Abstract base class for every CARBON tool adapter."""
from __future__ import annotations

from abc import ABC, abstractmethod

from carbon.core.result import ToolResult


class Adapter(ABC):
    name: str
    destructive: bool = False

    @abstractmethod
    def run(self, **params) -> ToolResult:
        """Execute the tool and return a structured result."""
