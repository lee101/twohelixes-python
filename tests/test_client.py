import asyncio
import time
from datetime import datetime, timezone

from twohelixes import AsyncTwohelixes, Events, Twohelixes


def test_batch_payload(server):
    c = Twohelixes("thw_test", api_url=server.url, flush_interval=60)
    c.track(Events.SIGN_UP_COMPLETED, {"method": "google"}, user_id="u1", session_id="s1",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), url="https://x.io/signup", referrer="https://g.co")
    c.identify("u1", {"plan": "pro"}, client_id="c1")
    c.purchase(19.0, "USD", transaction_id="txn_1", plan="pro", surface="paywall", user_id="u1", timestamp=1700000000.5)
    c.track("anon")
    c.flush()
    assert len(server.requests) == 1
    r = server.requests[0]
    assert r["path"] == "/v1/collect"
    body = server.bodies()[0]
    assert body["site_id"] == "thw_test"
    su, ident, buy, anon = body["events"]
    assert su == {"event": "sign_up_completed", "client_id": "u1", "user_id": "u1", "session_id": "s1",
                  "ts": 1767225600000, "page_location": "https://x.io/signup", "referrer": "https://g.co",
                  "props": {"method": "google"}}
    assert ident["type"] == "identify" and ident["event"] == "identify"
    assert ident["client_id"] == "c1" and ident["user_id"] == "u1" and ident["traits"] == {"plan": "pro"}
    assert buy["event"] == "purchase" and buy["event_id"] == "txn_1" and buy["ts"] == 1700000000500
    assert buy["props"] == {"revenue": 19.0, "currency": "USD", "transaction_id": "txn_1", "plan": "pro",
                            "surface": "paywall"}
    assert anon["client_id"] == c.anonymous_id and isinstance(anon["ts"], int) and "props" not in anon
    c.shutdown()


def test_flush_at_triggers_send(server):
    c = Twohelixes("thw_test", api_url=server.url, flush_at=3, flush_interval=60)
    for i in range(3):
        c.track("e", {"i": i})
    deadline = time.time() + 5
    while not server.requests and time.time() < deadline:
        time.sleep(0.01)
    assert len(server.events()) == 3
    c.shutdown()


def test_chunking(server):
    c = Twohelixes("thw_test", api_url=server.url, flush_at=10**6, flush_interval=60)
    for i in range(4500):
        c.track("e", user_id=str(i))
    c.flush()
    assert [len(b["events"]) for b in server.bodies()] == [2000, 2000, 500]
    c.shutdown()


def test_shutdown_flushes(server):
    with Twohelixes("thw_test", api_url=server.url, flush_interval=60) as c:
        c.page("https://x.io/", {"a": 1})
    assert server.events()[0]["event"] == "page_view"
    assert server.events()[0]["page_location"] == "https://x.io/"
    c.track("late")
    assert len(server.events()) == 1


def test_sync_mode(server):
    c = Twohelixes("thw_test", api_url=server.url, sync_mode=True)
    c.track("now")
    assert server.events()[0]["event"] == "now"


def test_unreachable_never_raises():
    errors = []
    c = Twohelixes("thw_test", api_url="http://127.0.0.1:1", flush_interval=60, timeout=1,
                   on_error=lambda exc, evs: errors.append((exc, evs)))
    c.track("x")
    c.flush()
    c.shutdown()
    assert len(errors) == 1 and errors[0][1][0]["event"] == "x"


def test_retry_then_error(server):
    server.status = 503
    errors = []
    c = Twohelixes("thw_test", api_url=server.url, sync_mode=True, on_error=lambda e, evs: errors.append(e))
    c.track("x")
    assert len(server.requests) == 2 and "503" in str(errors[0])
    server.status, server.requests[:] = 400, []
    c.track("y")
    assert len(server.requests) == 1 and len(errors) == 2


def test_bad_input_never_raises(server):
    errors = []
    c = Twohelixes("thw_test", api_url=server.url, sync_mode=True, on_error=lambda e, evs: errors.append(e))
    c.track("x", timestamp="nope")
    assert errors and not server.requests


def test_async_client(server):
    async def run():
        async with AsyncTwohelixes("thw_test", api_url=server.url, flush_at=2) as c:
            await c.track("a", user_id="u1")
            await c.track("b")
            assert len(server.events()) == 2
            await c.purchase(5, "EUR", transaction_id="t9")
            await c.identify("u2", {"x": 1})
        return c

    c = asyncio.run(run())
    ev = server.events()
    assert [e["event"] for e in ev] == ["a", "b", "purchase", "identify"]
    assert ev[0]["client_id"] == "u1" and ev[1]["client_id"] == c.anonymous_id and ev[2]["event_id"] == "t9"
