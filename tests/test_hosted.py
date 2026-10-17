"""The hosted version: the last 7 days' picks, the website's paywall, Stripe Checkout and the daily job.

Atlas and Stripe are replaced by fakes (Stripe's HTTP API by httpx.MockTransport), so no
test reaches a real service. Skipped unless the hosted extras are installed.
"""

import json
import re
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

pytest.importorskip("starlette")
pytest.importorskip("jinja2")
pytest.importorskip("pymongo")

from starlette.testclient import TestClient  # noqa: E402

from docscout.run.db import Store  # noqa: E402
from docscout.hosted import job  # noqa: E402
from docscout.hosted.billing import BillingError, Stripe  # noqa: E402
from docscout.hosted.picks import FREE_PICKS, weekly_picks  # noqa: E402
from docscout.hosted.web import COOKIE, create_app, sign_pass, valid_pass  # noqa: E402

SECRET = "test-secret"
PUBLIC = "https://docscout.test"


def details(name, *, description="Self-hosted uptime app", html_url=None, effort_units=None, findings=None):
    return {
        "api_type": "rest",
        "api_label": "REST",
        "head_sha": "0123456789abcdef0123456789abcdef01234567",
        "gap": {
            "kind": "spec", "score": 60, "location": "api/openapi.yaml", "summary": "OpenAPI 3.1, 38 operations, hand-written",
            "findings": findings or [{"text": "21/38 operations have no description", "examples": ["POST /checks"], "more": 20}],
            "suggestion": "Fill in the missing descriptions.", "published": ["Docs website: docs.example.dev"], "effort_units": effort_units,
        },
        "repo": {"stars": 412, "language": "Go", "description": description},
        "review": {"model": "openai_compatible:gemma-4-31b-it", "why": "Users need the webhook payloads.", "first_steps": ["Read CONTRIBUTING.md", "Describe POST /checks"]},
        "checks": {"claimed": [], "requirements": [], "local_setup": "easy (docker-compose)", "claim_checked": True},
        "issues": [{"number": 214, "title": "Document webhook payloads", "html_url": html_url or f"https://github.com/{name}/issues/214"}],
    }


def report(store, now, name, *, score=50.0, status="reported", **kw):
    run = store.start_run(now)
    store.save_repo(name, now, source="awesome_selfhosted")
    store.save_finding(run, name, now, api_type="rest", kind="spec", gap=60, score=score, effort="M", details=details(name, **kw))
    store.set_status(name, status, now)


def sample_picks(n):
    return [{"rank": i, "full_name": f"org/app{i}", "url": f"https://github.com/org/app{i}", "score": 90 - i, "stars": 100, "language": "Go",
             "description": None, "gap_heading": "REST API spec with gaps", "gap_summary": "OpenAPI 3.1", "gap_file": None, "gap_file_url": None,
             "findings": [], "headline": "OpenAPI 3.1", "effort": "Medium job", "outside_prs": 4, "suggestion": None, "published": [], "check_manually": [], "model": "Gemma", "why": None, "first_steps": [],
             "claimed": [], "requirements": [], "local_setup": None, "issues": []} for i in range(1, n + 1)]


class FakeAtlas:
    def __init__(self, picks=(), state=None):
        self.picks, self.updated, self.state, self.subscriptions = list(picks), None, state, {}

    def current_picks(self):
        return self.picks, self.updated

    def publish(self, picks, now):
        self.picks, self.updated = picks, now

    def record_subscription(self, subscription):
        self.subscriptions.setdefault(subscription["_id"], subscription)

    def load_state(self, path):
        if self.state is None:
            path.unlink(missing_ok=True)
            return False
        path.write_bytes(self.state)
        return True

    def save_state(self, path):
        self.state = path.read_bytes()


class FakeStripe:
    test_mode = True

    def __init__(self):
        self.paid = {"cs_test_paid0000000001": {"_id": "cs_test_paid0000000001", "subscription": "sub_1", "customer": "cus_1"}}

    def start_checkout(self, public_url):
        return "https://checkout.stripe.com/c/pay/cs_test_paid0000000001"

    def paid_session(self, session_id):
        return self.paid.get(session_id)


def client(atlas, stripe=None, now=1_800_000_000.0):
    app = create_app(atlas, stripe or FakeStripe(), secret=SECRET, public_url=PUBLIC, clock=lambda: now)
    return TestClient(app, base_url=PUBLIC)


# ---------------------------------------------------------------------- weekly picks


def test_weekly_picks_are_this_weeks_open_reports_with_only_trusted_links(tmp_path, now):
    store = Store(tmp_path / "docscout.db")
    report(store, now, "org/best", score=80, html_url="https://evil.example/phish", description=":baby: Line one\x1b[31m\u202e hidden")
    report(store, now, "org/second", score=40)
    report(store, now - timedelta(days=8), "org/old")  # reported last week
    report(store, now, "org/waiting", status="new")  # not reported yet
    report(store, now, "org/finished", status="done")
    picks = weekly_picks(store, now)
    assert [p["full_name"] for p in picks] == ["org/best", "org/second"] and [p["rank"] for p in picks] == [1, 2]
    best = picks[0]
    assert best["url"] == "https://github.com/org/best"
    assert best["gap_file_url"] == "https://github.com/org/best/blob/0123456789abcdef0123456789abcdef01234567/api/openapi.yaml"
    assert best["issues"] == [{"title": "#214 Document webhook payloads", "url": None}]  # not a GitHub link: text only
    assert best["description"] == "Line one hidden"  # control and bidi characters removed
    assert best["findings"] == ["21/38 operations have no description (e.g. POST /checks and 20 more)"]
    assert best["model"] == "Gemma" and best["first_steps"] == ["Read CONTRIBUTING.md", "Describe POST /checks"]
    assert best["published"] == ["Docs website: docs.example.dev"]


def test_picks_say_when_they_were_found_and_label_the_newest(tmp_path, now):
    store = Store(tmp_path / "docscout.db")
    two_days_ago, this_morning = now - timedelta(days=2), now - timedelta(hours=3)
    report(store, two_days_ago, "org/older", score=90)
    report(store, this_morning, "org/today", score=40)
    older, today = weekly_picks(store, now)  # still best first
    assert (older["full_name"], older["new"], today["new"]) == ("org/older", False, True)
    assert today["reported"] == this_morning.isoformat(timespec="seconds")
    assert older["found"] == f"{two_days_ago.day} {two_days_ago:%b}"


def test_gaps_too_small_to_be_worth_a_contribution_are_left_out(tmp_path, now):
    store = Store(tmp_path / "docscout.db")
    report(store, now, "org/big", effort_units=21)
    report(store, now, "org/tiny", score=90, effort_units=1)  # reported before the cutoff existed
    report(store, now, "org/unknown", score=30)  # size unknown: kept
    assert [p["full_name"] for p in weekly_picks(store, now, min_units=5)] == ["org/big", "org/unknown"]


def test_the_headline_is_the_biggest_gap(tmp_path, now):
    store = Store(tmp_path / "docscout.db")
    report(store, now, "org/app", findings=[
        {"text": "2/19 endpoints have no description", "examples": ["GET /a", "GET /b"], "more": 0},
        {"text": "19/19 endpoints have no response example", "examples": ["GET /a", "GET /b"], "more": 17},
    ])
    assert weekly_picks(store, now)[0]["headline"] == "19/19 endpoints have no response example"


# ---------------------------------------------------------------------- website


def test_visitors_see_the_top_picks_and_an_offer_for_the_rest():
    resp = client(FakeAtlas(sample_picks(7))).get("/")
    assert resp.status_code == 200
    assert resp.text.count('class="card pick"') == FREE_PICKS
    assert f"{7 - FREE_PICKS} more projects to choose from" in resp.text and 'action="/subscribe"' in resp.text
    assert f"org/app{FREE_PICKS}<" in resp.text and f"org/app{FREE_PICKS + 1}<" not in resp.text  # the rest never reach the page
    assert "4242 4242 4242 4242" in resp.text  # test mode is labeled
    csp = resp.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src" not in csp  # no scripts allowed at all


def test_text_from_github_is_escaped():
    picks = sample_picks(1)
    picks[0].update(description='<script>alert(1)</script>', why='"><img src=x onerror=alert(1)>', url=None)
    resp = client(FakeAtlas(picks)).get("/")
    assert "<script>alert" not in resp.text and "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text
    assert "<img src=x" not in resp.text
    assert 'href="None"' not in resp.text and "<a href" not in resp.text.split('class="card pick"')[1].split("</li>")[0]


def test_a_paid_checkout_unlocks_every_pick():
    atlas = FakeAtlas(sample_picks(7))
    c = client(atlas)
    start = c.post("/subscribe", follow_redirects=False)
    assert start.status_code == 303 and start.headers["location"].startswith("https://checkout.stripe.com/")
    back = c.get("/subscribed", params={"session_id": "cs_test_paid0000000001"}, follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"] == "/"
    assert "HttpOnly" in back.headers["set-cookie"] and "Secure" in back.headers["set-cookie"]
    assert "cs_test_paid0000000001" in atlas.subscriptions
    page = c.get("/")
    assert page.text.count('class="card pick"') == 7 and "more project" not in page.text and "every pick is shown" in page.text


def test_subscribers_page_through_every_pick():
    c = client(FakeAtlas(sample_picks(23)))
    c.cookies.set(COOKIE, sign_pass("cs_test_paid0000000001", 2_000_000_000, SECRET))
    first = c.get("/").text
    assert first.count('class="card pick"') == 10 and "Page 1 of 3" in first and 'href="/?page=2#picks"' in first
    last = c.get("/?page=3").text
    assert last.count('class="card pick"') == 3 and "org/app21" in last and "org/app20" not in last
    assert "Page 3 of 3" in c.get("/?page=99").text  # past the end: the last page
    assert "Page 1 of 3" in c.get("/?page=-2").text and "Page 1 of 3" in c.get("/?page=abc").text
    visitor = client(FakeAtlas(sample_picks(23))).get("/?page=2").text
    assert visitor.count('class="card pick"') == FREE_PICKS and "org/app1<" in visitor and "Page 2" not in visitor  # no pages behind the paywall


def test_subscribers_can_see_the_newest_first_and_visitors_keep_the_best():
    picks = sample_picks(12)
    for p in picks:
        p["reported"] = "2026-10-16T04:15:00+00:00"
    picks[10]["reported"] = picks[11]["reported"] = "2026-10-17T04:15:00+00:00"  # ranks 11 and 12 are the newest
    picks[11]["new"] = True
    c = client(FakeAtlas(picks))
    c.cookies.set(COOKIE, sign_pass("cs_test_paid0000000001", 2_000_000_000, SECRET))
    best = c.get("/").text
    assert re.findall(r">(org/app\d+)</a>", best)[:2] == ["org/app1", "org/app2"] and 'href="/?sort=latest#picks"' in best
    latest = c.get("/?sort=latest").text
    assert re.findall(r">(org/app\d+)</a>", latest)[:3] == ["org/app11", "org/app12", "org/app1"]  # newest day, then best first
    assert 'href="/?page=2&amp;sort=latest#picks"' in latest and latest.count('class="chip new"') == 1  # pages keep the order
    visitor = client(FakeAtlas(picks)).get("/?sort=latest").text
    assert re.findall(r">(org/app\d+)</a>", visitor) == [f"org/app{i}" for i in range(1, FREE_PICKS + 1)]
    assert "?sort=latest" not in visitor  # sorting is for subscribers


def test_unpaid_or_forged_returns_unlock_nothing():
    atlas = FakeAtlas(sample_picks(7))
    c = client(atlas)
    back = c.get("/subscribed", params={"session_id": "cs_test_unpaid000000001"}, follow_redirects=False)
    assert back.headers["location"] == "/?payment=failed" and "set-cookie" not in back.headers and atlas.subscriptions == {}
    assert "go through, so nothing was charged" in c.get("/?payment=failed").text
    forged = client(atlas)
    forged.cookies.set(COOKIE, "cs_test_x.9999999999.deadbeef")
    assert forged.get("/").text.count('class="card pick"') == FREE_PICKS


def test_a_pass_is_valid_only_until_it_expires():
    token = sign_pass("cs_test_paid0000000001", 2_000, SECRET)
    assert valid_pass(token, SECRET, now=1_999) and not valid_pass(token, SECRET, now=2_000)
    assert not valid_pass(token, "another-secret", now=1_000)
    assert not valid_pass(token.replace("2000", "9000"), SECRET, now=1_000)  # a longer pass can't be forged


def test_payments_being_down_says_so_instead_of_failing():
    class Down(FakeStripe):
        def start_checkout(self, public_url):
            raise BillingError("Stripe error 500")

    c = client(FakeAtlas(sample_picks(7)), Down())
    assert c.post("/subscribe", follow_redirects=False).headers["location"] == "/?payment=unavailable"


# ---------------------------------------------------------------------- Stripe


def test_checkout_asks_stripe_for_a_2_dollar_monthly_subscription():
    sent = []

    def handler(req):
        sent.append((req.method, req.url.path, dict(httpx.QueryParams(req.content.decode()))))
        return httpx.Response(200, json={"url": "https://checkout.stripe.com/c/pay/cs_test_abc"})

    url = Stripe("sk_test_123", transport=httpx.MockTransport(handler)).start_checkout("https://docscout.test/")
    assert url == "https://checkout.stripe.com/c/pay/cs_test_abc"
    method, path, form = sent[0]
    assert (method, path) == ("POST", "/v1/checkout/sessions")
    assert form["mode"] == "subscription" and form["line_items[0][price_data][unit_amount]"] == "200"
    assert form["line_items[0][price_data][recurring][interval]"] == "month"
    assert form["success_url"] == "https://docscout.test/subscribed?session_id={CHECKOUT_SESSION_ID}"


def test_only_a_complete_paid_session_counts_and_no_email_is_kept():
    sessions = {
        "cs_test_paid0000000001": {"id": "cs_test_paid0000000001", "status": "complete", "payment_status": "paid", "subscription": "sub_1",
                                   "customer": "cus_1", "customer_details": {"email": "writer@example.com"}, "livemode": False, "created": 1},
        "cs_test_open0000000001": {"id": "cs_test_open0000000001", "status": "open", "payment_status": "unpaid"},
    }
    calls = []

    def handler(req):
        calls.append(req.url.path)
        sid = req.url.path.rsplit("/", 1)[1]
        return httpx.Response(200, json=sessions[sid]) if sid in sessions else httpx.Response(404, json={})

    stripe = Stripe("sk_test_123", transport=httpx.MockTransport(handler))
    paid = stripe.paid_session("cs_test_paid0000000001")
    assert paid == {"_id": "cs_test_paid0000000001", "subscription": "sub_1", "customer": "cus_1", "livemode": False, "created": 1}
    assert "writer@example.com" not in json.dumps(paid)
    assert stripe.paid_session("cs_test_open0000000001") is None
    assert stripe.paid_session("cs_test_missing00000001") is None
    calls.clear()
    assert stripe.paid_session("../../v1/customers") is None and calls == []  # not a session id: Stripe isn't asked


# ---------------------------------------------------------------------- daily job


def test_the_hosted_settings_check_more_than_a_laptop_run():
    from docscout.settings.config import load_config

    cfg = load_config(Path(__file__).parents[1] / "deploy" / "render.toml")
    assert cfg["discovery"]["daily_repo_budget"] == 200 and cfg["llm"]["reviews_per_run"] == 30 and cfg["report"]["max_items"] == 30
    assert cfg["llm"]["model"] == "gemma-4-31b-it" and cfg["notifications"]["run_finished"] is False


def test_the_daily_job_keeps_docscouts_memory_in_atlas(tmp_path, now, monkeypatch):
    from docscout import cli
    from docscout.settings import config

    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    seen_args = []

    def first_run(argv):
        seen_args.append(argv)
        assert not (tmp_path / "docscout.db").exists()  # nothing in Atlas yet
        store = Store(tmp_path / "docscout.db")
        report(store, now, "org/app")
        store.close()
        return 0

    atlas = FakeAtlas()
    monkeypatch.setattr(cli, "main", first_run)
    assert job.main(atlas=atlas) == 0
    assert seen_args == [["--config", "deploy/render.toml", "run"]]
    assert atlas.state and [p["full_name"] for p in atlas.picks] == ["org/app"]

    def next_run(argv):
        assert Store(tmp_path / "docscout.db").repo("org/app")["status"] == "reported"  # memory restored
        raise RuntimeError("connection lost")

    (tmp_path / "docscout.db").unlink()
    monkeypatch.setattr(cli, "main", next_run)
    with pytest.raises(RuntimeError):
        job.main(atlas=atlas)
    assert atlas.state and len(atlas.picks) == 1  # saved and published even after a failed run
