from __future__ import annotations

import asyncio
import atexit
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Union

from . import _http

log = logging.getLogger("twohelixes")

MAX_BATCH = 2000
RETRY_BACKOFF = 0.5

Timestamp = Union[datetime, float, int, None]
OnError = Callable[[Exception, List[Dict[str, Any]]], None]


class SendError(Exception):
    pass


def _ms(t: Timestamp) -> int:
    if t is None:
        return int(time.time() * 1000)
    if isinstance(t, datetime):
        t = t.timestamp()
    return int(round(t * 1000))


class _Core:
    def __init__(self, write_key, api_url, flush_at, max_queue, timeout, on_error):
        self.write_key = write_key or os.environ.get("TWOHELIXES_WRITE_KEY")
        self.api_url = _http.api_url(api_url)
        self.flush_at = max(1, flush_at)
        self.max_queue = max_queue
        self.timeout = timeout
        self.on_error = on_error
        self.anonymous_id = "c_" + uuid.uuid4().hex[:20]
        self._queue: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        if not self.write_key:
            log.warning("twohelixes: no write key (TWOHELIXES_WRITE_KEY); events will be dropped")

    def _event(self, event, props=None, *, client_id=None, user_id=None, session_id=None,
               event_id=None, timestamp=None, url=None, referrer=None, _extra=None) -> Dict[str, Any]:
        e: Dict[str, Any] = {
            "event": event,
            "client_id": client_id or user_id or self.anonymous_id,
            "ts": _ms(timestamp),
        }
        for k, v in (("user_id", user_id), ("session_id", session_id), ("event_id", event_id),
                     ("page_location", url), ("referrer", referrer)):
            if v is not None:
                e[k] = v
        if props:
            e["props"] = dict(props)
        e.update(_extra or {})
        return e

    def _identify(self, user_id, traits=None, client_id=None, timestamp=None):
        return self._event("identify", client_id=client_id, user_id=user_id, timestamp=timestamp,
                           _extra={"type": "identify", "traits": dict(traits or {})})

    def _purchase(self, revenue, currency, transaction_id=None, plan=None, surface=None, props=None, **kw):
        p: Dict[str, Any] = {"revenue": revenue, "currency": currency}
        for k, v in (("transaction_id", transaction_id), ("plan", plan), ("surface", surface)):
            if v is not None:
                p[k] = v
        p.update(props or {})
        kw.setdefault("event_id", transaction_id)
        return self._event("purchase", p, **kw)

    def _enqueue(self, e: Dict[str, Any]) -> int:
        if not self.write_key:
            return 0
        with self._lock:
            if len(self._queue) >= self.max_queue:
                self._fail(SendError("queue full, event dropped"), [e])
                return len(self._queue)
            self._queue.append(e)
            return len(self._queue)

    def _drain(self) -> List[Dict[str, Any]]:
        with self._lock:
            q, self._queue = self._queue, []
            return q

    def _fail(self, exc: Exception, events: List[Dict[str, Any]]) -> None:
        if self.on_error:
            try:
                self.on_error(exc, events)
                return
            except Exception:
                log.exception("twohelixes: on_error raised")
        log.warning("twohelixes: dropped %d events: %s", len(events), exc)

    def _send(self, events: List[Dict[str, Any]]) -> None:
        for i in range(0, len(events), MAX_BATCH):
            self._post(events[i:i + MAX_BATCH])

    def _post(self, chunk: List[Dict[str, Any]]) -> None:
        body = {"site_id": self.write_key, "events": chunk}
        err: Exception = SendError("unknown")
        for attempt in range(2):
            if attempt:
                time.sleep(RETRY_BACKOFF)
            try:
                status, raw = _http.request("POST", self.api_url + "/v1/collect", body, timeout=self.timeout)
            except Exception as e:
                err = e
                continue
            if status < 300:
                return
            err = SendError(f"HTTP {status}: {raw[:200].decode(errors='replace')}")
            if status < 500:
                break
        self._fail(err, chunk)


class Twohelixes(_Core):
    def __init__(self, write_key: Optional[str] = None, api_url: Optional[str] = None, flush_at: int = 20,
                 flush_interval: float = 5.0, max_queue: int = 10000, timeout: float = 10,
                 on_error: Optional[OnError] = None, sync_mode: bool = False):
        super().__init__(write_key, api_url, flush_at, max_queue, timeout, on_error)
        self.flush_interval = flush_interval
        self.sync_mode = sync_mode
        self._send_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if not sync_mode:
            self._thread = threading.Thread(target=self._run, name="twohelixes", daemon=True)
            self._thread.start()
            atexit.register(self.shutdown)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self.flush_interval)
            self._wake.clear()
            self.flush()

    def _add(self, e: Dict[str, Any]) -> None:
        if self._stop.is_set():
            self._fail(SendError("client shut down"), [e])
        elif self.sync_mode:
            if self.write_key:
                self._send([e])
        elif self._enqueue(e) >= self.flush_at:
            self._wake.set()

    def _safe(self, build: Callable[[], Dict[str, Any]]) -> None:
        try:
            self._add(build())
        except Exception as exc:
            self._fail(exc, [])

    def track(self, event: str, props: Optional[Dict[str, Any]] = None, *, client_id: Optional[str] = None,
              user_id: Optional[str] = None, session_id: Optional[str] = None, event_id: Optional[str] = None,
              timestamp: Timestamp = None, url: Optional[str] = None, referrer: Optional[str] = None) -> None:
        self._safe(lambda: self._event(event, props, client_id=client_id, user_id=user_id, session_id=session_id,
                                       event_id=event_id, timestamp=timestamp, url=url, referrer=referrer))

    def identify(self, user_id: str, traits: Optional[Dict[str, Any]] = None, client_id: Optional[str] = None) -> None:
        self._safe(lambda: self._identify(user_id, traits, client_id))

    def page(self, url: str, props: Optional[Dict[str, Any]] = None, **kw: Any) -> None:
        self.track("page_view", props, url=url, **kw)

    def purchase(self, revenue: float, currency: str, *, transaction_id: Optional[str] = None,
                 plan: Optional[str] = None, surface: Optional[str] = None, **kw: Any) -> None:
        self._safe(lambda: self._purchase(revenue, currency, transaction_id, plan, surface, **kw))

    def flush(self) -> None:
        with self._send_lock:
            q = self._drain()
            if q:
                try:
                    self._send(q)
                except Exception as exc:
                    self._fail(exc, q)

    def shutdown(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(self.timeout * 2 + 1)
        self.flush()
        try:
            atexit.unregister(self.shutdown)
        except Exception:
            pass

    close = shutdown

    def __enter__(self) -> "Twohelixes":
        return self

    def __exit__(self, *_: Any) -> None:
        self.shutdown()


class AsyncTwohelixes(_Core):
    def __init__(self, write_key: Optional[str] = None, api_url: Optional[str] = None, flush_at: int = 20,
                 max_queue: int = 10000, timeout: float = 10, on_error: Optional[OnError] = None):
        super().__init__(write_key, api_url, flush_at, max_queue, timeout, on_error)
        self._alock: Optional[asyncio.Lock] = None

    async def _add(self, build: Callable[[], Dict[str, Any]]) -> None:
        try:
            if self._enqueue(build()) >= self.flush_at:
                await self.flush()
        except Exception as exc:
            self._fail(exc, [])

    async def track(self, event: str, props: Optional[Dict[str, Any]] = None, *, client_id: Optional[str] = None,
                    user_id: Optional[str] = None, session_id: Optional[str] = None, event_id: Optional[str] = None,
                    timestamp: Timestamp = None, url: Optional[str] = None, referrer: Optional[str] = None) -> None:
        await self._add(lambda: self._event(event, props, client_id=client_id, user_id=user_id, session_id=session_id,
                                            event_id=event_id, timestamp=timestamp, url=url, referrer=referrer))

    async def identify(self, user_id: str, traits: Optional[Dict[str, Any]] = None,
                       client_id: Optional[str] = None) -> None:
        await self._add(lambda: self._identify(user_id, traits, client_id))

    async def page(self, url: str, props: Optional[Dict[str, Any]] = None, **kw: Any) -> None:
        await self.track("page_view", props, url=url, **kw)

    async def purchase(self, revenue: float, currency: str, *, transaction_id: Optional[str] = None,
                       plan: Optional[str] = None, surface: Optional[str] = None, **kw: Any) -> None:
        await self._add(lambda: self._purchase(revenue, currency, transaction_id, plan, surface, **kw))

    async def flush(self) -> None:
        if self._alock is None:
            self._alock = asyncio.Lock()
        async with self._alock:
            q = self._drain()
            if q:
                try:
                    await asyncio.get_running_loop().run_in_executor(None, self._send, q)
                except Exception as exc:
                    self._fail(exc, q)

    async def aclose(self) -> None:
        await self.flush()

    async def __aenter__(self) -> "AsyncTwohelixes":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()
