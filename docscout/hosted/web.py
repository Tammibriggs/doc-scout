"""The website: this week's picks, the top few free and the rest for subscribers.

Run it with ``uvicorn --factory docscout.hosted.web:from_env``. It reads, from the environment:
``MONGODB_URI``, ``STRIPE_SECRET_KEY``, ``SESSION_SECRET`` (signs the subscriber cookie) and
``PUBLIC_URL`` (where Stripe sends people back).

The page uses no JavaScript, so its Content-Security-Policy allows no scripts at all.
The paywall is enforced here, on the server: a visitor's page only ever contains the picks
they may see. Templates escape every value (Jinja2 autoescape), and links are only the
GitHub URLs prepared in :mod:`docscout.hosted.picks`.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from docscout.hosted.billing import PRICE_CENTS, BillingError
from docscout.hosted.picks import FREE_PICKS
from docscout.sanitize import is_github_url

COOKIE = "docscout_pass"
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
        picks, updated = atlas.current_picks()
        subscribed = valid_pass(request.cookies.get(COOKIE), secret, clock())
        shown = picks if subscribed else picks[:FREE_PICKS]
        return page(
            request,
            picks=shown,
            hidden=len(picks) - len(shown),
            total=len(picks),
            subscribed=subscribed,
            updated=updated,
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

    key = os.environ["STRIPE_SECRET_KEY"]
    stripe = Stripe(key)
    stripe.test_mode = not key.startswith("sk_live_")  # type: ignore[attr-defined]
    return create_app(
        Atlas(os.environ["MONGODB_URI"]),
        stripe,
        secret=os.environ["SESSION_SECRET"],
        public_url=os.environ["PUBLIC_URL"],
        source_url=os.environ.get("SOURCE_URL"),
    )
