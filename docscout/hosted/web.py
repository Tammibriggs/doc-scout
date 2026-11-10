"""The website: every open pick, the best 3 found this week free and the rest for subscribers.

Run it with ``uvicorn --factory docscout.hosted.web:from_env``. It reads, from the environment:
``MONGODB_URI``, ``STRIPE_SECRET_KEY``, ``SESSION_SECRET`` (signs the subscriber cookie) and
``PUBLIC_URL`` (where Stripe sends people back).

The page uses no JavaScript, so its Content-Security-Policy allows no scripts at all.
The paywall is enforced here, on the server: a visitor's page only ever contains the picks
they may see. Atlas keeps each pick in two parts, joined when read (:mod:`docscout.hosted.atlas`),
and a page asks only for what it shows: the free picks, a page of 10, or the fields the search reads.
Templates escape every value (Jinja2 autoescape), and links are only the GitHub URLs prepared in
:mod:`docscout.hosted.picks`.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from docscout.hosted import atlas_database, required_secret
from docscout.hosted.billing import PRICE_CENTS, BillingError
from docscout.hosted.picks import EFFORT, FREE_PICKS
from docscout.hosted.search import MAX_QUERY, search, suggestions
from docscout.run.sanitize import clean, is_github_url

COOKIE = "docscout_pass"
PER_PAGE = 10  # picks per page for subscribers
# Subscribers' filters (8 Nov): the job's size, and only picks whose maintainers asked for help.
# Visitors get none, since a filter would show them picks beyond the free 3. Anyone can search
# (hosted.search): subscribers see what matches, visitors how many match and the free ones that do.
SIZES = {"small": "S", "medium": "M", "big": "L"}
SIZE_CHOICES = [(None, "Any size"), ("small", "Small"), ("medium", "Medium"), ("big", "Big")]
PASS_SECONDS = 31 * 24 * 3600  # a month's subscription, plus a day
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "form-action 'self' https://checkout.stripe.com; base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))



def ago(iso: str | None, now: float) -> str | None:
    """"2 hours ago", for when a pick was last checked; None when unknown."""
    from datetime import datetime

    if not iso:
        return None
    try:
        seconds = now - datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return None
    if seconds < 3600:
        return "within the hour"
    hours = int(seconds // 3600)
    if hours < 48:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    return f"{hours // 24} days ago"

def picks_link(*, page: int = 1, sort: str = "best", size: str | None = None, help_only: bool = False, q: str | None = None) -> str:
    """The list's address with these choices: only the ones that differ from the defaults."""
    params = [("q", q)] if q else []
    params += [("page", str(page))] if page > 1 else []
    params += [("sort", "latest")] if sort == "latest" else []
    params += [("size", size)] if size in SIZES else []
    params += [("help", "1")] if help_only else []
    return ("/?" + urlencode(params) if params else "/") + "#picks"


def sign_pass(subscription_id: str, expires: int, secret: str) -> str:
    payload = f"{subscription_id}.{expires}"
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{mac}"


def valid_pass(token: str | None, secret: str, now: float) -> bool:
    """True for an unexpired pass this server signed."""
    parts = (token or "").split(".")
    if len(parts) != 3 or not parts[1].isdigit():
        return False
    subscription_id, expires, mac = parts
    expected = hmac.new(secret.encode(), f"{subscription_id}.{expires}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, expected) and int(expires) > now


def create_app(
    atlas: Any, stripe: Any, *, secret: str, public_url: str, source_url: str | None = None, clock: Callable[[], float] = time.time
) -> Starlette:
    secure_cookie = public_url.startswith("https://")
    source_url = source_url if source_url and is_github_url(source_url) else None

    def page(request: Request, status: int = 200, **context: Any) -> Response:
        resp = templates.TemplateResponse(request, "index.html", context, status_code=status)
        resp.headers.update(SECURITY_HEADERS)
        return resp

    async def index(request: Request) -> Response:
        # Atlas keeps each pick in two parts (hosted.atlas): the page asks only for what it shows
        listing = atlas.listing()
        total = listing.count
        subscribed = valid_pass(request.cookies.get(COOKIE), secret, clock())
        pages, number, sort, size, help_only = 1, 1, "best", None, False
        q = clean(request.query_params.get("q", "")[:MAX_QUERY], MAX_QUERY) or None  # cut, not shortened with "…"
        free = total
        searched: list[dict[str, Any]] = []  # what a suggested search looks through: the searched fields only
        found: list[str] = []  # the names a search matched, in order
        if subscribed:  # pages of PER_PAGE; visitors see only the free picks, so they need no pages, sorting or filters
            where: dict[str, Any] = {}
            if request.query_params.get("sort") == "latest":  # newest first, then best first within a day
                sort = "latest"
            if request.query_params.get("size") in SIZES:
                size = request.query_params["size"]
                where["effort"] = EFFORT[SIZES[size]]
            if request.query_params.get("help") == "1":
                help_only = True
                where["asked_for_help"] = True  # the "Maintainers asked for help" chip
            if q:  # searched in memory over four fields; the page's picks are then asked for by name
                searched = atlas.list_picks(listing, where, sort, searched_only=True)
                found = [p["full_name"] for p in search(searched, q)]
                matching = len(found)
            else:
                matching = atlas.count_picks(listing, where)
            pages = max(1, math.ceil(matching / PER_PAGE))
            requested = request.query_params.get("page", "1")
            number = min(pages, max(1, int(requested))) if requested.isdigit() else 1
            start = (number - 1) * PER_PAGE
            if q:
                shown = atlas.picks_named(listing, found[start : start + PER_PAGE])
            else:
                shown = atlas.list_picks(listing, where, sort, skip=start, limit=PER_PAGE)
        else:  # the free picks (M6: the best found this week); a list published before has no flags
            shown = atlas.free_picks(listing, FREE_PICKS)
            free, matching = len(shown), total
            if q:  # how many of all the picks match, and the free ones among them
                searched = atlas.list_picks(listing, searched_only=True)
                matched = {p["full_name"] for p in search(searched, q)}
                matching = len(matched)
                shown = [p for p in shown if p.get("full_name") in matched]
        shown = [{**p, "checked_ago": ago(p.get("checked"), clock())} for p in shown]

        def link(**changes: Any) -> str:  # the current choices, with some changed; a change starts again at page 1
            return picks_link(**{"sort": sort, "size": size, "help_only": help_only, "q": q, **changes})

        return page(
            request,
            picks=shown,
            hidden=0 if subscribed else matching - len(shown),
            free=free,
            q=q,
            suggestions=suggestions(searched) if q and not matching else [],
            page_number=number,
            pages=pages,
            sort=sort,
            size=size,
            help_only=help_only,
            filtered=bool(size or help_only or q),
            active_count=int(bool(size)) + int(help_only),
            size_name=dict(SIZE_CHOICES).get(size),
            matching=matching,
            sizes=SIZE_CHOICES,
            link=link,
            total=total,
            subscribed=subscribed,
            updated=listing.updated,
            price=f"${PRICE_CENTS / 100:.0f}",
            test_mode=getattr(stripe, "test_mode", True),
            source_url=source_url,
            notice={"failed": "The payment didn't go through, so nothing was charged.", "unavailable": "Payments aren't available right now. Please try again later."}.get(
                request.query_params.get("payment", "")
            ),
        )

    async def subscribe(request: Request) -> Response:
        try:
            url = stripe.start_checkout(public_url)
        except BillingError:
            return RedirectResponse("/?payment=unavailable", status_code=303)
        return RedirectResponse(url, status_code=303)

    async def subscribed(request: Request) -> Response:
        session = stripe.paid_session(request.query_params.get("session_id", ""))
        if session is None:
            return RedirectResponse("/?payment=failed", status_code=303)
        atlas.record_subscription(session)
        resp = RedirectResponse("/", status_code=303)
        expires = int(clock()) + PASS_SECONDS
        resp.set_cookie(COOKIE, sign_pass(session["_id"], expires, secret), max_age=PASS_SECONDS, httponly=True, secure=secure_cookie, samesite="lax")
        return resp

    async def healthz(request: Request) -> Response:
        return PlainTextResponse("ok")

    return Starlette(
        routes=[
            Route("/", index),
            Route("/subscribe", subscribe, methods=["POST"]),
            Route("/subscribed", subscribed),
            Route("/healthz", healthz),
        ]
    )


def from_env() -> Starlette:
    from docscout.hosted.atlas import Atlas
    from docscout.hosted.billing import Stripe

    key = required_secret("STRIPE_SECRET_KEY")
    stripe = Stripe(key)
    stripe.test_mode = not key.startswith("sk_live_")  # type: ignore[attr-defined]
    return create_app(
        Atlas(required_secret("MONGODB_URI"), database=atlas_database()),
        stripe,
        secret=required_secret("SESSION_SECRET"),
        public_url=os.environ.get("PUBLIC_URL", "http://localhost:8000"),
        source_url=os.environ.get("SOURCE_URL", "https://github.com/Tammibriggs/doc-scout"),
    )
