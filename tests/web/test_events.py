# SPDX-License-Identifier: GPL-3.0-or-later
import queue
import time

import pytest

from carbon.web.events import Broker


def test_subscribe_receives_published():
    b = Broker()
    with b.subscribe() as sub:
        b.publish({"type": "x"})
        assert sub.get(timeout=1) == {"type": "x"}


def test_multiple_subscribers_all_receive():
    b = Broker()
    with b.subscribe() as s1, b.subscribe() as s2:
        b.publish({"n": 1})
        assert s1.get(timeout=1) == {"n": 1}
        assert s2.get(timeout=1) == {"n": 1}


def test_unsubscribe_stops_delivery():
    b = Broker()
    with b.subscribe() as sub:
        pass
    b.publish({"n": 1})
    with pytest.raises(queue.Empty):
        sub.get(timeout=0.05)


def test_publish_never_blocks_on_full_queue():
    b = Broker(maxsize=4)
    with b.subscribe() as sub:
        t = time.monotonic()
        for i in range(100):
            b.publish({"i": i})
        assert time.monotonic() - t < 1
        got = [sub.get(timeout=0.1)["i"] for _ in range(4)]
        assert got == [96, 97, 98, 99]  # drop-oldest


def test_registered_on_subscribe_before_enter():
    b = Broker()
    sub = b.subscribe()
    b.publish({"n": 1})  # before entering the with block
    with sub:
        assert sub.get(timeout=1) == {"n": 1}
    sub.unsubscribe()  # idempotent
    sub.unsubscribe()


def test_maxsize_clamped_stays_bounded():
    b = Broker(maxsize=0)
    with b.subscribe() as sub:
        for i in range(10):
            b.publish({"i": i})
        assert sub.get(timeout=0.1) == {"i": 9}
        with pytest.raises(queue.Empty):
            sub.get(timeout=0.05)
