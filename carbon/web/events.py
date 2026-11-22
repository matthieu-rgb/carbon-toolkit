# SPDX-License-Identifier: GPL-3.0-or-later
"""In-process pub/sub broker used to push live events to SSE clients.

``publish`` never blocks and never raises: each subscriber has a bounded
queue and, when full, the oldest event is dropped to make room.
"""
from __future__ import annotations

import queue
import threading


class Subscription:
    """One subscriber. ``get(timeout)`` raises ``queue.Empty`` on timeout."""

    def __init__(self, broker: "Broker", maxsize: int) -> None:
        self._broker = broker
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)

    def get(self, timeout: float):
        return self._q.get(timeout=timeout)

    def unsubscribe(self) -> None:
        self._broker._remove(self)

    def _offer(self, event: dict) -> None:
        try:
            self._q.put_nowait(event)
        except queue.Full:
            try:
                self._q.get_nowait()  # drop oldest
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(event)
            except queue.Full:
                pass  # lost a race; drop the event

    def __enter__(self) -> "Subscription":
        self._broker._add(self)
        return self

    def __exit__(self, *exc) -> None:
        self.unsubscribe()


class Broker:
    def __init__(self, maxsize: int = 256) -> None:
        self._maxsize = maxsize
        self._lock = threading.Lock()
        self._subs: set[Subscription] = set()

    def subscribe(self) -> Subscription:
        """Create a subscription; it registers on ``__enter__`` (or via
        ``with``). Use as ``with broker.subscribe() as sub:``."""
        return Subscription(self, self._maxsize)

    def _add(self, sub: Subscription) -> None:
        with self._lock:
            self._subs.add(sub)

    def _remove(self, sub: Subscription) -> None:
        with self._lock:
            self._subs.discard(sub)

    def publish(self, event: dict) -> None:
        try:
            with self._lock:
                subs = list(self._subs)
            for s in subs:
                try:
                    s._offer(event)
                except Exception:
                    pass
        except Exception:
            pass
