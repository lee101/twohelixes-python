from __future__ import annotations

import asyncio
import functools
import json
import os
import urllib.parse
from typing import Any, Dict, Optional, Sequence, Union

from . import _http


class TwohelixesError(Exception):
    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(f"{status} {code}: {detail}" if detail else f"{status} {code}")
        self.status = status
        self.code = code
        self.detail = detail


Steps = Union[str, Sequence[str]]


class Reports:
    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None, timeout: float = 60):
        self.api_key = api_key or os.environ.get("TWOHELIXES_API_KEY")
        if not self.api_key:
            raise ValueError("twohelixes: api_key required (or set TWOHELIXES_API_KEY)")
        self.api_url = _http.api_url(api_url)
        self.timeout = timeout

    def _call(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, body: Any = None) -> Any:
        url = self.api_url + path
        q = {k: v for k, v in (params or {}).items() if v is not None}
        if q:
            url += "?" + urllib.parse.urlencode(q)
        try:
            status, raw = _http.request(method, url, body, {"Authorization": f"Bearer {self.api_key}"}, self.timeout)
        except OSError as e:
            raise TwohelixesError(0, "network_error", str(e)) from e
        text = raw.decode(errors="replace")
        try:
            data = json.loads(text) if text.strip() else None
        except ValueError:
            data = text
        if status >= 300:
            if isinstance(data, dict):
                code = str(data.get("error") or "http_error")
                detail = str(data.get("detail") or data.get("message") or "")
            else:
                code, detail = "http_error", text[:500]
            raise TwohelixesError(status, code, detail)
        return data

    def _get(self, endpoint: str, site_id: Optional[str] = None, days: Optional[int] = None, **params: Any) -> Any:
        return self._call("GET", "/v1/analytics/" + endpoint, {"site_id": site_id, "days": days, **params})

    def sites(self) -> Any:
        return self._get("sites")

    def summary(self, site_id: str, days: int = 30) -> Any:
        return self._get("summary", site_id, days)

    def timeseries(self, site_id: str, days: int = 30) -> Any:
        return self._get("timeseries", site_id, days)

    def events(self, site_id: str, days: int = 30, limit: int = 100) -> Any:
        return self._get("events", site_id, days, limit=limit)

    def schema(self, site_id: str, days: int = 30, event: Optional[str] = None) -> Any:
        return self._get("schema", site_id, days, event=event)

    def paths(self, site_id: str, days: int = 30, mode: str = "both", start: Optional[str] = None,
              depth: int = 5, limit: int = 20) -> Any:
        return self._get("paths", site_id, days, mode=mode, start=start, depth=depth, limit=limit)

    def revenue(self, site_id: str, days: int = 30) -> Any:
        return self._get("revenue", site_id, days)

    def funnel(self, site_id: str, steps: Steps, days: int = 30) -> Any:
        return self._get("funnel", site_id, days, steps=steps if isinstance(steps, str) else ",".join(steps))

    def groups(self, site_id: str, type: Optional[str] = None, days: int = 30) -> Any:
        return self._get("groups", site_id, days, type=type)

    def export(self, site_id: str, days: int = 1, limit: Optional[int] = None) -> Any:
        return self._get("export", site_id, days, limit=limit)

    def ask(self, site_id: str, question: str, days: int = 30) -> Any:
        return self._call("POST", "/v1/query", body={"q": question, "analytics_site_id": site_id, "days": days})


def _async(name: str) -> Any:
    fn = getattr(Reports, name)

    @functools.wraps(fn)
    async def wrapper(self: "AsyncReports", *args: Any, **kwargs: Any) -> Any:
        call = functools.partial(fn, self._sync, *args, **kwargs)
        return await asyncio.get_running_loop().run_in_executor(None, call)

    return wrapper


class AsyncReports:
    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None, timeout: float = 60):
        self._sync = Reports(api_key, api_url, timeout)

    sites = _async("sites")
    summary = _async("summary")
    timeseries = _async("timeseries")
    events = _async("events")
    schema = _async("schema")
    paths = _async("paths")
    revenue = _async("revenue")
    funnel = _async("funnel")
    groups = _async("groups")
    export = _async("export")
    ask = _async("ask")

    async def aclose(self) -> None:
        pass

    async def __aenter__(self) -> "AsyncReports":
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass
