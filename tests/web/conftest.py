# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import itertools
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from carbon.emu.ecu import SimulatedEcu
from carbon.web.app import create_web_runtime
from carbon.web.security import new_web_token

_counter = itertools.count()


class Live:
    def __init__(self, port, token, session, queue, broker):
        self.port, self.session, self.queue, self.broker = port, session, queue, broker
        self.base = f"http://127.0.0.1:{port}"
        self.headers = {"Origin": self.base}
        self.cookies = {"carbon_web": token}

    def client(self, **kw):
        return httpx.Client(base_url=self.base, cookies=self.cookies, timeout=15, **kw)

    def post(self, url, **kw):
        with self.client() as c:
            return c.post(url, headers=self.headers, **kw)

    def sse(self, max_events, budget=10.0):
        """Read up to max_events SSE events (bounded by a wall-clock budget)."""
        out, ev = [], None
        end = time.monotonic() + budget
        with httpx.Client(base_url=self.base, cookies=self.cookies,
                          timeout=httpx.Timeout(budget)) as c:
            with c.stream("GET", "/api/events") as r:
                assert r.headers["content-type"].startswith("text/event-stream")
                for line in r.iter_lines():
                    if line.startswith("event: "):
                        ev = line[7:]
                    elif line.startswith("data: ") and ev:
                        out.append((ev, json.loads(line[6:])))
                        ev = None
                        if len(out) >= max_events:
                            break
                    if time.monotonic() > end:
                        break
        return out


class SseReader:
    """Persistent SSE connection read in a thread; wait_for(type) is bounded."""

    def __init__(self, live):
        self.events, self._cv = [], threading.Condition()
        self._stop = threading.Event()
        self._r = None
        self._t = threading.Thread(target=self._run, args=(live,), daemon=True)
        self._t.start()

    def _run(self, live):
        ev = None
        try:
            with httpx.Client(base_url=live.base, cookies=live.cookies,
                              timeout=httpx.Timeout(30)) as c:
                with c.stream("GET", "/api/events") as r:
                    for line in r.iter_lines():
                        if self._stop.is_set():
                            return
                        if line.startswith("event: "):
                            ev = line[7:]
                        elif line.startswith("data: ") and ev:
                            with self._cv:
                                self.events.append((ev, json.loads(line[6:])))
                                self._cv.notify_all()
                            ev = None
        except Exception:
            pass

    def wait_for(self, etype, timeout=10.0, pred=lambda d: True, start=0):
        end = time.monotonic() + timeout
        with self._cv:
            while True:
                for e, d in self.events[start:]:
                    if e == etype and pred(d):
                        return d
                left = end - time.monotonic()
                if left <= 0:
                    raise AssertionError(f"no {etype} event; got {self.events}")
                self._cv.wait(left)

    def close(self):
        self._stop.set()


@pytest.fixture
def channel() -> str:
    return f"carbon-web-live-{next(_counter)}"


@pytest.fixture
def ecu(channel):
    with SimulatedEcu(channel, interface="virtual") as e:
        assert e.ready.is_set()
        yield e


def _start(channel, tmp_path, approval_timeout):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    token = new_web_token()
    app, session, queue, broker = create_web_runtime(
        channel=channel, interface="virtual", journal_path=tmp_path / "j.jsonl",
        token=token, port=port, approval_timeout=approval_timeout, heartbeat=0.2)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    end = time.monotonic() + 10
    while not server.started and time.monotonic() < end:
        time.sleep(0.02)
    assert server.started
    return Live(port, token, session, queue, broker), server, t


@pytest.fixture
def make_live(channel, tmp_path):
    started = []

    def make(approval_timeout=30.0):
        live, server, t = _start(channel, tmp_path, approval_timeout)
        started.append((server, t))
        return live

    yield make
    for server, t in started:
        server.should_exit = True
        t.join(10)


@pytest.fixture
def live(make_live):
    return make_live()
