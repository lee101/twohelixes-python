# twohelixes-python

Tiny, zero-dependency Python client for [twoHelixes](https://twohelixes.com) product analytics:
server-side event tracking (sync + asyncio) and the reporting API (funnels, paths, revenue, natural-language queries).

- stdlib only (`urllib`), Python 3.9+
- background batching thread, `flush_at` / `flush_interval`, chunked to 2,000 events per request, one retry on 5xx/network errors
- `track()` never raises; failures go to `on_error` or the `twohelixes` logger
- typed (`py.typed`)

## Install

```sh
uv add git+https://github.com/lee101/twohelixes-python
# or
pip install git+https://github.com/lee101/twohelixes-python
```

Keys: a write key (`thw_...`, ingest only, safe to ship) and an API key (`th_...`, reporting, keep secret).
Both fall back to `TWOHELIXES_WRITE_KEY` / `TWOHELIXES_API_KEY`; `TWOHELIXES_API_URL` overrides `https://twohelixes.com` for self-hosting.

## Quickstart

```python
from twohelixes import Twohelixes, Events

th = Twohelixes("thw_xxx")  # flushes every 5s or 20 events; flushed on exit

th.track(Events.SIGN_UP_STARTED, {"method": "google", "surface": "hero_cta"}, client_id="c_7f3a")
th.identify("user_42", {"plan": "free"}, client_id="c_7f3a")
th.page("https://app.example.com/dashboard", user_id="user_42")
```

Flask:

```python
from flask import Flask, request
from twohelixes import Twohelixes, Events

app = Flask(__name__)
th = Twohelixes("thw_xxx")

@app.post("/signup")
def signup():
    user = create_user(request.form)
    cid = request.cookies.get("th_cid")  # the browser client id, if you use th.js
    th.track(Events.SIGN_UP_COMPLETED, {"method": "email", "surface": request.form.get("surface")},
             client_id=cid, user_id=user.id, url=request.url, referrer=request.referrer)
    th.identify(user.id, {"email_domain": user.email.split("@")[1]}, client_id=cid)
    return {"ok": True}
```

Serverless / short-lived processes: `Twohelixes("thw_xxx", sync_mode=True)` sends each event immediately,
or call `th.flush()` before returning.

## Canonical SaaS funnel

Use the [`Events`](src/twohelixes/events.py) constants so funnels, dashboards and the agent line up across products.
Carry the same `surface` (the UI placement that triggered the step) from `paywall_open` through `purchase`.

```python
from twohelixes import Events

th.track(Events.SIGN_UP_COMPLETED, {"method": "google", "surface": "signup_page"}, user_id=uid, client_id=cid)
th.identify(uid, {"plan": "free"}, client_id=cid)

th.track(Events.PAYWALL_OPEN, {"surface": "export_button", "plan": "pro"}, user_id=uid)
th.track(Events.BEGIN_CHECKOUT, {"plan": "pro", "value": 19.0, "currency": "USD", "surface": "export_button"},
         user_id=uid)
```

Fire `purchase` from the payment webhook, with the transaction id as `event_id` so retries collapse:

```python
@app.post("/stripe/webhook")
def stripe_webhook():
    event = stripe.Webhook.construct_event(request.data, request.headers["Stripe-Signature"], WHSEC)
    if event["type"] == "checkout.session.completed":
        s = event["data"]["object"]
        th.purchase(
            s["amount_total"] / 100,           # major units
            s["currency"].upper(),
            transaction_id=s["id"],            # also used as event_id
            plan=s["metadata"].get("plan"),
            surface=s["metadata"].get("surface"),
            user_id=s["client_reference_id"],
        )
    return "", 200
```

Refunds: `th.track(Events.REFUND, {"revenue": 19.0, "currency": "USD", "transaction_id": "re_xxx"}, event_id="re_xxx", user_id=uid)`.

## Async

```python
from twohelixes import AsyncTwohelixes

async with AsyncTwohelixes("thw_xxx", flush_at=50) as th:
    await th.track("sign_up_completed", {"surface": "nav"}, user_id="user_42")
    await th.purchase(19.0, "USD", transaction_id="cs_123", plan="pro", user_id="user_42")
```

FastAPI:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from twohelixes import AsyncTwohelixes

th = AsyncTwohelixes("thw_xxx")

@asynccontextmanager
async def lifespan(app):
    yield
    await th.aclose()

app = FastAPI(lifespan=lifespan)

@app.post("/paywall")
async def paywall(user_id: str, surface: str):
    await th.track("paywall_open", {"surface": surface}, user_id=user_id)
```

Events are buffered in memory and sent when `flush_at` is reached or on `flush()` / `aclose()`.

## Reporting

```python
from twohelixes import Reports, TwohelixesError

r = Reports("th_xxx")
site = r.sites()["sites"][0]["id"]

r.summary(site, days=30)
r.revenue(site)
r.paths(site, mode="events", start="paywall_open", depth=6)

f = r.funnel(site, ["page_view:/signup", "sign_up_started", "sign_up_completed|sign_in_completed",
                    "paywall_open", "begin_checkout", "purchase"], days=30)

print(r.ask(site, "which paywall surfaces convert best?"))  # natural language, spends credits

try:
    r.summary("nope")
except TwohelixesError as e:
    print(e.status, e.code, e.detail)
```

Funnel steps are passed through verbatim (comma-joined if you pass a list), so qualifiers like
`page_view:/signup` and alternatives like `sign_up_completed|sign_in_completed` work as the server defines them.

Methods: `sites`, `summary`, `timeseries`, `events`, `schema`, `paths`, `revenue`, `funnel`, `groups`, `export`, `ask`.
`AsyncReports` has the same methods as coroutines.

## Agents / MCP

Query the same data from Claude Code or any MCP client with [twohelixes-cli](https://github.com/lee101/twohelixes-cli):

```sh
claude mcp add twohelixes -- twohelixes-cli mcp
```

API reference: [twohelixes.com](https://twohelixes.com).

## Development

```sh
uv sync
uv run pytest -q
uv build
```

## License

MIT
