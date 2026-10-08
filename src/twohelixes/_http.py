from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Mapping, Optional, Tuple

DEFAULT_API_URL = "https://twohelixes.com"
USER_AGENT = "twohelixes-python/0.1.0"


def api_url(url: Optional[str]) -> str:
    return (url or os.environ.get("TWOHELIXES_API_URL") or DEFAULT_API_URL).rstrip("/")


def request(
    method: str,
    url: str,
    body: Any = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = 10,
) -> Tuple[int, bytes]:
    data = None if body is None else json.dumps(body, separators=(",", ":"), default=str).encode()
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
