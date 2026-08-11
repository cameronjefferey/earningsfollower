"""Cross-product isolation on a shared Stripe account.

The Stripe account behind this app is shared with sibling products, and Stripe
delivers the whole account's event stream to every registered webhook endpoint.
Sibling products number their users from 1 too, so a foreign event can carry a
user_id or client_reference_id that matches one of our users. Nothing may touch
a user row unless the object carries one of our own price ids.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api import billing
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db
from app.main import app

OURS_MONTHLY = "price_ef_monthly"
OURS_ANNUAL = "price_ef_annual"
FOREIGN = "price_happytrader_monthly"


class FakeResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class FakeDB:
    """Minimal Session stand-in: id lookups hit, every query misses.

    Query misses mirror production for a foreign event, whose Stripe customer
    id is not on any of our rows, forcing the metadata/client_reference_id
    fallback that the collision exploits.
    """

    def __init__(self, users_by_id: dict[int, User]):
        self.users_by_id = users_by_id
        self.committed = False

    def scalars(self, _stmt):
        return FakeResult(None)

    def get(self, _model, pk):
        return self.users_by_id.get(int(pk))

    def add(self, _obj):
        pass

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


def _paying_user() -> User:
    return User(
        id=10,
        email="real-customer@example.com",
        stripe_customer_id="cus_ours",
        stripe_subscription_id="sub_ours",
        subscription_status="active",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=20),
    )


def _settings(price_ids: str = OURS_ANNUAL) -> Settings:
    return Settings(
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        stripe_price_id=OURS_MONTHLY,
        stripe_price_ids=price_ids,
    )


def _subscription(sub_id: str, price_id: str, *, status: str, user_id: str) -> dict:
    return {
        "id": sub_id,
        "object": "subscription",
        "status": status,
        "customer": "cus_stranger",
        "current_period_end": 2000000000,
        "metadata": {"user_id": user_id},
        "items": {"data": [{"id": "si_1", "price": {"id": price_id}}]},
    }


def _override_db(db: FakeDB):
    def _gen():
        yield db

    return _gen


def _post_event(event: dict, db: FakeDB, settings) -> int:
    client = TestClient(app)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        with patch.object(billing, "_construct_event", return_value=event), patch.object(
            billing, "log_event"
        ):
            res = client.post(
                "/billing/webhook",
                headers={"stripe-signature": "t=1,v1=stub"},
                json={},
            )
        return res.status_code
    finally:
        app.dependency_overrides.clear()


def test_foreign_checkout_completed_writes_nothing():
    """HappyTrader user #10 buying HappyTrader must not touch our user #10."""
    user = _paying_user()
    user.subscription_status = "none"
    user.stripe_customer_id = None
    user.stripe_subscription_id = None
    user.current_period_end = None
    db = FakeDB({10: user})
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_foreign",
                "customer": "cus_stranger",
                "subscription": "sub_foreign",
                "client_reference_id": "10",
                "metadata": {"user_id": "10"},
            }
        },
    }
    foreign_sub = _subscription(
        "sub_foreign", FOREIGN, status="active", user_id="10"
    )
    with patch.object(
        billing.stripe.Subscription, "retrieve", return_value=foreign_sub
    ):
        status = _post_event(event, db, _settings())

    assert status == 200
    assert user.stripe_customer_id is None
    assert user.stripe_subscription_id is None
    assert user.subscription_status == "none"


def test_foreign_subscription_deleted_does_not_revoke_paying_customer():
    """The expensive direction: a stranger's cancellation churning our customer."""
    user = _paying_user()
    db = FakeDB({10: user})
    event = {
        "type": "customer.subscription.deleted",
        "data": {
            "object": _subscription(
                "sub_foreign", FOREIGN, status="canceled", user_id="10"
            )
        },
    }
    assert _post_event(event, db, _settings()) == 200
    assert user.subscription_status == "active"
    assert user.stripe_subscription_id == "sub_ours"
    assert user.stripe_customer_id == "cus_ours"


def test_our_checkout_completed_still_grants_access():
    user = _paying_user()
    user.subscription_status = "none"
    user.stripe_customer_id = None
    user.stripe_subscription_id = None
    user.current_period_end = None
    db = FakeDB({10: user})
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_ours",
                "customer": "cus_new",
                "subscription": "sub_new",
                "client_reference_id": "10",
                "metadata": {"user_id": "10"},
            }
        },
    }
    our_sub = _subscription("sub_new", OURS_ANNUAL, status="active", user_id="10")
    with patch.object(billing.stripe.Subscription, "retrieve", return_value=our_sub):
        assert _post_event(event, db, _settings()) == 200

    assert user.stripe_customer_id == "cus_new"
    assert user.stripe_subscription_id == "sub_new"
    assert user.subscription_status == "active"


def test_checkout_without_subscription_does_not_bind_customer():
    user = _paying_user()
    user.stripe_customer_id = None
    db = FakeDB({10: user})
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_payment_mode",
                "customer": "cus_stranger",
                "client_reference_id": "10",
                "metadata": {"user_id": "10"},
            }
        },
    }
    assert _post_event(event, db, _settings()) == 200
    assert user.stripe_customer_id is None


def test_ownership_fails_closed_without_configured_prices():
    settings = Settings(stripe_price_id="", stripe_price_ids="")
    assert settings.stripe_owned_price_ids == frozenset()
    sub = _subscription("sub_x", OURS_MONTHLY, status="active", user_id="1")
    assert billing.subscription_is_ours(sub, settings) is False


def test_invoice_price_ids_read_both_api_shapes():
    legacy = {"lines": {"data": [{"price": {"id": OURS_MONTHLY}}]}}
    modern = {
        "lines": {
            "data": [{"pricing": {"price_details": {"price": OURS_ANNUAL}}}]
        }
    }
    assert billing._invoice_price_ids(legacy) == {OURS_MONTHLY}
    assert billing._invoice_price_ids(modern) == {OURS_ANNUAL}


def test_foreign_invoice_paid_is_ignored():
    user = _paying_user()
    user.subscription_status = "none"
    db = FakeDB({10: user})
    event = {
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_foreign",
                "customer": "cus_stranger",
                "amount_paid": 1999,
                "metadata": {"user_id": "10"},
                "parent": {
                    "subscription_details": {"subscription": "sub_foreign"}
                },
                "lines": {
                    "data": [
                        {"pricing": {"price_details": {"price": FOREIGN}}}
                    ]
                },
            }
        },
    }
    foreign_sub = _subscription(
        "sub_foreign", FOREIGN, status="active", user_id="10"
    )
    with patch.object(
        billing.stripe.Subscription, "retrieve", return_value=foreign_sub
    ):
        assert _post_event(event, db, _settings()) == 200
    assert user.subscription_status == "none"
    assert user.stripe_subscription_id == "sub_ours"


def test_sync_ignores_sibling_product_subscription():
    """Same person, both products, one Stripe customer: only our price counts."""
    settings = _settings()
    foreign = _subscription("sub_foreign", FOREIGN, status="active", user_id="10")
    with patch.object(
        billing.stripe.Subscription, "list", return_value={"data": [foreign]}
    ):
        assert billing._pick_subscription("cus_shared", settings) is None
