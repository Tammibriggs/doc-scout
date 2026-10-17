"""Stripe Checkout through Stripe's HTTP API: a $3 monthly subscription.

Test-mode keys (``sk_test_…``) work the same way and never charge a card; Stripe's test card
is 4242 4242 4242 4242. A subscription counts only after DocScout has asked Stripe itself
that the Checkout Session is complete and paid, so a forged return link unlocks nothing.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

API = "https://api.stripe.com/v1"
PRICE_CENTS = 200
PRODUCT_NAME = "DocScout: every pick, every week"
_SESSION_ID = re.compile(r"^cs_(test|live)_[A-Za-z0-9]{10,200}$")


class BillingError(Exception):
    pass


class Stripe:
    def __init__(self, secret_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=API, auth=(secret_key, ""), timeout=20, transport=transport)

    def start_checkout(self, public_url: str) -> str:
        """A Checkout page for the subscription; returns its URL."""
        base = public_url.rstrip("/")
        data = {
            "mode": "subscription",
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": "usd",
            "line_items[0][price_data][unit_amount]": str(PRICE_CENTS),
            "line_items[0][price_data][recurring][interval]": "month",
            "line_items[0][price_data][product_data][name]": PRODUCT_NAME,
            "success_url": f"{base}/subscribed?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{base}/",
        }
        try:
            resp = self._client.post("/checkout/sessions", data=data)
        except httpx.HTTPError as exc:
            raise BillingError(f"can't reach Stripe: {exc}") from exc
        if resp.status_code != 200:
            raise BillingError(f"Stripe error {resp.status_code}: {resp.text[:200]}")
        return str(resp.json()["url"])

    def paid_session(self, session_id: str) -> dict[str, Any] | None:
        """The subscription record for a completed, paid Checkout Session, or None."""
        if not _SESSION_ID.match(session_id or ""):
            return None
        try:
            resp = self._client.get(f"/checkout/sessions/{session_id}")
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        session = resp.json()
        if session.get("status") != "complete" or session.get("payment_status") not in ("paid", "no_payment_required"):
            return None
        return {
            "_id": session["id"],
            "subscription": session.get("subscription"),
            "customer": session.get("customer"),
            "livemode": bool(session.get("livemode")),
            "created": session.get("created"),
        }
