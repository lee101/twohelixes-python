import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from twohelixes import AsyncReports, Reports, TwohelixesError


def q(server, i=-1):
    u = urlsplit(server.requests[i]["path"])
    return u.path, {k: v[0] for k, v in parse_qs(u.query).items()}


def test_bearer_and_query(server):
    server.status, server.response = 200, b'{"sites":[{"id":"s1"}]}'
    r = Reports("th_test", api_url=server.url)
    assert r.sites() == {"sites": [{"id": "s1"}]}
    assert server.requests[0]["headers"]["Authorization"] == "Bearer th_test"
    assert q(server) == ("/v1/analytics/sites", {})
    r.paths("s1", days=7, mode="events", start="paywall_open", depth=6)
    assert q(server) == ("/v1/analytics/paths", {"site_id": "s1", "days": "7", "mode": "events",
                                                  "start": "paywall_open", "depth": "6", "limit": "20"})
    r.schema("s1")
    assert q(server) == ("/v1/analytics/schema", {"site_id": "s1", "days": "30"})


def test_funnel_steps_verbatim(server):
    server.status, server.response = 200, b"{}"
    r = Reports("th_test", api_url=server.url)
    steps = "page_view:/signup,sign_up_completed|sign_in_completed"
    r.funnel("s1", steps)
    assert q(server)[1]["steps"] == steps
    r.funnel("s1", ["page_view:/signup", "sign_up_completed|sign_in_completed"], days=14)
    assert q(server) == ("/v1/analytics/funnel", {"site_id": "s1", "days": "14", "steps": steps})


def test_ask(server):
    server.status, server.response = 200, b'{"answer":"ok"}'
    assert Reports("th_test", api_url=server.url).ask("s1", "why?", days=7) == {"answer": "ok"}
    req = server.requests[0]
    assert req["method"] == "POST" and req["path"] == "/v1/query"
    assert json.loads(req["body"]) == {"q": "why?", "analytics_site_id": "s1", "days": 7}


@pytest.mark.parametrize("status,body,code,detail", [
    (401, b'{"error":"unauthorized","detail":"bad key"}', "unauthorized", "bad key"),
    (404, b'{"error":"not_found","message":"no site"}', "not_found", "no site"),
    (500, b"boom", "http_error", "boom"),
])
def test_errors(server, status, body, code, detail):
    server.status, server.response = status, body
    with pytest.raises(TwohelixesError) as ei:
        Reports("th_test", api_url=server.url).summary("s1")
    assert (ei.value.status, ei.value.code, ei.value.detail) == (status, code, detail)


def test_missing_key(monkeypatch):
    monkeypatch.delenv("TWOHELIXES_API_KEY", raising=False)
    with pytest.raises(ValueError):
        Reports()


def test_env_fallback(server, monkeypatch):
    monkeypatch.setenv("TWOHELIXES_API_KEY", "th_env")
    monkeypatch.setenv("TWOHELIXES_API_URL", server.url + "/")
    server.status, server.response = 200, b"[]"
    assert Reports().revenue("s1") == []
    assert server.requests[0]["headers"]["Authorization"] == "Bearer th_env"


def test_async_reports(server):
    server.status, server.response = 200, b'{"steps":[]}'

    async def run():
        async with AsyncReports("th_test", api_url=server.url) as r:
            return await r.funnel("s1", ["a", "b|c"])

    assert asyncio.run(run()) == {"steps": []}
    assert q(server)[1]["steps"] == "a,b|c"
