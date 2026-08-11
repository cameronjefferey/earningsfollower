from __future__ import annotations

import logging
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, OptionalAuth, subscription_is_active
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db
from app.services.admin_events import log_event
from app.services.signup_alerts import notify_signup

logger = logging.getLogger("earningsfollower.billing")

router = APIRouter(prefix="/billing", tags=["billing"])

_ACTIVE = frozenset({"active", "trialing"})

# Stamped on new checkouts/subscriptions purely so support can eyeball which
# product a Stripe object came from. Entitlement is decided by price id, since
# subscriptions created before this marker existed have empty metadata.
APP_MARKER = "earningsfollower"


class CheckoutBody(BaseModel):
    success_url: str | None = None
    cancel_url: str | None = None


class PortalBody(BaseModel):
    return_url: str | None = None


def _stripe(settings: Settings) -> None:
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    stripe.api_key = settings.stripe_secret_key


def _require_signed_in(caller: AuthUser | None) -> AuthUser:
    if caller is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return caller


def _get_or_create_user(db: Session, caller: AuthUser) -> User:
    user = caller.db_user
    if user is None:
        user = db.scalars(select(User).where(User.email == caller.email)).first()
    if user is None:
        user = User(email=caller.email, name=caller.name, google_sub=caller.sub)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _ensure_stripe_customer(user: User, settings: Settings) -> str:
    _stripe(settings)
    if user.stripe_customer_id and _customer_exists(user.stripe_customer_id):
        return user.stripe_customer_id
    if user.stripe_customer_id:
        # Test-mode leftover after flipping to live keys.
        _clear_stripe_ids(user)
    # Prefer an existing Stripe customer for this email (avoids duplicates after
    # a webhook miss left our row without stripe_customer_id).
    existing = _list_data(stripe.Customer.list(email=user.email, limit=1))
    if existing:
        user.stripe_customer_id = _field(existing[0], "id")
        return user.stripe_customer_id
    customer = stripe.Customer.create(
        email=user.email,
        name=user.name or None,
        metadata={"user_id": str(user.id)},
    )
    user.stripe_customer_id = customer["id"]
    return customer["id"]


def _clear_stripe_ids(user: User) -> None:
    """Drop Stripe ids that don't exist in the current mode (e.g. test→live)."""
    user.stripe_customer_id = None
    user.stripe_subscription_id = None
    user.subscription_status = "none"
    user.current_period_end = None


def _customer_exists(customer_id: str) -> bool:
    try:
        stripe.Customer.retrieve(customer_id)
        return True
    except stripe.InvalidRequestError:
        return False


def _resolve_customer_id(user: User) -> str | None:
    if user.stripe_customer_id:
        # Stale ids from the other Stripe mode (test vs live) look valid in our
        # DB but 404 in the API - clear them so the user can re-subscribe cleanly.
        if _customer_exists(user.stripe_customer_id):
            return user.stripe_customer_id
        logger.warning(
            "Clearing stale Stripe customer %s for %s (not in current mode)",
            user.stripe_customer_id,
            user.email,
        )
        _clear_stripe_ids(user)
    customers = _list_data(stripe.Customer.list(email=user.email, limit=1))
    if not customers:
        return None
    user.stripe_customer_id = _field(customers[0], "id")
    return user.stripe_customer_id


def _as_dict(obj: object) -> dict:
    """Normalize Stripe objects / dicts to a plain mapping.

    Newer stripe-python builds return StripeObject instances that do not always
    expose dict.get(), which previously crashed the webhook after a successful
    Checkout payment.
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    try:
        return dict(obj)  # type: ignore[arg-type]
    except Exception:
        return {}


def _list_data(obj: object) -> list:
    """Extract the ``data`` array from a Stripe list response safely."""
    data = _as_dict(obj).get("data")
    if isinstance(data, list):
        return data
    # ListObject is often directly iterable even when .get is broken.
    try:
        return list(obj)  # type: ignore[arg-type]
    except Exception:
        return []


def _field(obj: object, key: str, default=None):
    data = _as_dict(obj)
    return data.get(key, default)


def _items(container: object, key: str = "items") -> list:
    """Return the ``data`` array of a nested Stripe list (items, lines, ...)."""
    value = _as_dict(container).get(key)
    if isinstance(value, list):
        return value
    return _list_data(value) if value is not None else []


def _price_id(obj: object) -> str | None:
    """Pull a price id off a subscription item or invoice line.

    Shapes seen in the wild:
      subscription item: price.id (or the legacy plan.id)
      invoice line <2025-03: price.id
      invoice line 2025-03+: pricing.price_details.price (a bare id string)
    """
    data = _as_dict(obj)
    for key in ("price", "plan"):
        node = data.get(key)
        if isinstance(node, str) and node:
            return node
        node_id = _field(node, "id")
        if isinstance(node_id, str) and node_id:
            return node_id
    details = _as_dict(_as_dict(data.get("pricing")).get("price_details"))
    price = details.get("price")
    if isinstance(price, str) and price:
        return price
    return None


def _subscription_price_ids(sub: object) -> set[str]:
    data = _as_dict(sub)
    ids = {_price_id(item) for item in _items(data)}
    # Deleted/canceled subs sometimes arrive with only the legacy root plan.
    ids.add(_price_id({"plan": data.get("plan")}))
    return {p for p in ids if p}


def _invoice_price_ids(invoice: object) -> set[str]:
    ids = {_price_id(line) for line in _items(invoice, "lines")}
    return {p for p in ids if p}


def is_ours(price_ids: set[str], settings: Settings) -> bool:
    """Does this object belong to EarningsFollower?

    The Stripe account is shared with sibling products and Stripe fans the whole
    account's event stream out to every registered endpoint, so we must confirm
    a price id we sell before touching a user row. Fails closed: with nothing
    configured we own nothing.
    """
    owned = settings.stripe_owned_price_ids
    if not owned:
        return False
    return bool(price_ids & owned)


def subscription_is_ours(sub: object, settings: Settings) -> bool:
    return is_ours(_subscription_price_ids(sub), settings)


def _skip_foreign(etype: str, object_id: object, price_ids: set[str]) -> None:
    """Foreign-product traffic is expected here, so it is INFO, never ERROR."""
    logger.info(
        "Ignoring %s for another product on the shared Stripe account "
        "(object=%s, prices=%s)",
        etype,
        object_id,
        sorted(price_ids) or "none",
    )


def _period_end_ts(sub: dict) -> int | None:
    """Stripe API 2024+ may put period bounds on items, not the subscription root."""
    end = sub.get("current_period_end")
    if end:
        return int(end)
    items = sub.get("items")
    item_list = []
    if isinstance(items, dict):
        item_list = items.get("data") or []
    elif isinstance(items, list):
        item_list = items
    for item in item_list:
        item_data = _as_dict(item)
        if item_data.get("current_period_end"):
            return int(item_data["current_period_end"])
    return None


def _apply_subscription(user: User, sub: object) -> None:
    data = _as_dict(sub)
    user.stripe_subscription_id = data.get("id")
    user.subscription_status = data.get("status") or "none"
    end_ts = _period_end_ts(data)
    if end_ts:
        user.current_period_end = datetime.fromtimestamp(end_ts, tz=timezone.utc)
    else:
        user.current_period_end = None


def _pick_subscription(customer_id: str, settings: Settings) -> object | None:
    """Best subscription for this customer, ignoring sibling products.

    One person can legitimately buy EarningsFollower and a sibling product with
    the same email, which puts both subscriptions on the same Stripe customer.
    Only our own prices may drive entitlement.
    """
    subs = _list_data(
        stripe.Subscription.list(customer=customer_id, status="all", limit=10)
    )
    chosen = None
    for sub in subs:
        if not subscription_is_ours(sub, settings):
            _skip_foreign(
                "subscription sync",
                _field(sub, "id"),
                _subscription_price_ids(sub),
            )
            continue
        if _field(sub, "status") in _ACTIVE:
            return sub
        if chosen is None:
            chosen = sub
    return chosen


def _user_access_payload(user: User, settings: Settings, *, synced: bool) -> dict:
    status = user.subscription_status or "none"
    subscribed = subscription_is_active(
        email=user.email,
        status=status,
        period_end=user.current_period_end,
        settings=settings,
    )
    return {
        "subscribed": subscribed,
        "subscription_status": status,
        "synced": synced,
        "stripe_customer_id": user.stripe_customer_id,
        "stripe_subscription_id": user.stripe_subscription_id,
        "current_period_end": (
            user.current_period_end.isoformat() if user.current_period_end else None
        ),
    }


def _sync_user_from_stripe(user: User, settings: Settings) -> dict:
    """Pull Stripe state into the user row. Caller commits."""
    _stripe(settings)
    customer_id = _resolve_customer_id(user)
    if not customer_id:
        return _user_access_payload(user, settings, synced=False)

    chosen = _pick_subscription(customer_id, settings)
    if chosen is not None:
        _apply_subscription(user, chosen)
    return _user_access_payload(user, settings, synced=True)


def _construct_event(payload: bytes, sig: str, secrets: list[str]):
    last_exc: Exception | None = None
    for secret in secrets:
        try:
            return stripe.Webhook.construct_event(payload, sig, secret)
        except stripe.SignatureVerificationError as exc:
            last_exc = exc
            continue
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid payload") from exc
    logger.warning(
        "Stripe webhook signature failed against %d secret(s)", len(secrets)
    )
    notify_signup(
        "webhook_fail",
        f"Stripe webhook signature failed ({len(secrets)} secret(s) tried)",
        debounce_key="webhook_sig",
        debounce_s=900,
    )
    raise HTTPException(status_code=400, detail="Invalid signature") from last_exc


@router.get("/config")
def billing_config(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "paywall_enabled": settings.paywall_enabled,
        "stripe_configured": bool(settings.stripe_secret_key and settings.stripe_price_id),
        "price_id_set": bool(settings.stripe_price_id),
    }


@router.post("/checkout-session")
def create_checkout_session(
    body: CheckoutBody,
    caller: OptionalAuth,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    caller = _require_signed_in(caller)
    if not settings.stripe_price_id:
        raise HTTPException(status_code=503, detail="STRIPE_PRICE_ID is not configured")
    _stripe(settings)

    user = _get_or_create_user(db, caller)
    try:
        # If they already paid, don't start a second subscription - send portal.
        access = _sync_user_from_stripe(user, settings)
        db.commit()
        if access["subscribed"]:
            app_url = settings.public_app_url.rstrip("/")
            portal = stripe.billing_portal.Session.create(
                customer=user.stripe_customer_id,
                return_url=body.success_url or f"{app_url}/account",
            )
            return {
                "url": portal["url"],
                "id": portal["id"],
                "already_subscribed": True,
            }

        customer_id = _ensure_stripe_customer(user, settings)
        db.commit()

        app_url = settings.public_app_url.rstrip("/")
        success = body.success_url or f"{app_url}/pricing?checkout=success"
        cancel = body.cancel_url or f"{app_url}/pricing?checkout=cancel"

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
            success_url=success,
            cancel_url=cancel,
            client_reference_id=str(user.id),
            metadata={"user_id": str(user.id), "email": user.email, "app": APP_MARKER},
            subscription_data={"metadata": {"app": APP_MARKER, "user_id": str(user.id)}},
            allow_promotion_codes=True,
        )
        log_event(
            db,
            kind="stripe_checkout_started",
            email=user.email,
            message=f"Checkout started: {user.email}",
            meta={"session_id": session.get("id")},
            debounce_s=0,
        )
        db.commit()
    except stripe.InvalidRequestError as exc:
        logger.exception("Stripe checkout invalid request")
        detail = str(exc.user_message or exc) or "Stripe rejected checkout"
        log_event(
            db,
            kind="stripe_checkout_fail",
            email=user.email,
            message=f"Checkout failed for {user.email}: {detail}",
            debounce_key=f"checkout_fail:{user.email}",
            debounce_s=60,
        )
        db.commit()
        raise HTTPException(status_code=400, detail=detail) from exc
    except stripe.StripeError as exc:
        logger.exception("Stripe checkout failed")
        detail = str(exc.user_message or exc) or "Stripe checkout failed"
        log_event(
            db,
            kind="stripe_checkout_fail",
            email=user.email,
            message=f"Checkout failed for {user.email}: {detail}",
            debounce_key=f"checkout_fail:{user.email}",
            debounce_s=60,
        )
        db.commit()
        raise HTTPException(status_code=502, detail=detail) from exc
    return {"url": session["url"], "id": session["id"], "already_subscribed": False}


@router.post("/portal-session")
def create_portal_session(
    body: PortalBody,
    caller: OptionalAuth,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    caller = _require_signed_in(caller)
    _stripe(settings)
    user = _get_or_create_user(db, caller)
    try:
        customer_id = _resolve_customer_id(user)
        db.commit()
        if not customer_id:
            raise HTTPException(
                status_code=400,
                detail="No Stripe customer on this account yet - subscribe first",
            )
        app_url = settings.public_app_url.rstrip("/")
        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=body.return_url or f"{app_url}/account",
        )
    except HTTPException:
        raise
    except stripe.InvalidRequestError as exc:
        logger.exception("Stripe portal invalid request for %s", user.email)
        # Common after flipping test→live: DB still has the sandbox customer id.
        if "No such customer" in str(exc):
            _clear_stripe_ids(user)
            db.commit()
            raise HTTPException(
                status_code=400,
                detail=(
                    "Your billing account was from Stripe test mode and isn't in "
                    "live mode. Subscribe again to manage billing."
                ),
            ) from exc
        raise HTTPException(
            status_code=400,
            detail=str(exc.user_message or exc) or "Stripe rejected the portal",
        ) from exc
    except stripe.StripeError as exc:
        logger.exception("Stripe portal failed for %s", user.email)
        raise HTTPException(
            status_code=502,
            detail=str(exc.user_message or exc) or "Could not open billing portal",
        ) from exc
    return {"url": portal["url"]}


@router.post("/sync")
def sync_subscription(
    caller: OptionalAuth,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Pull live Stripe subscription state into the user row.

    Used after Checkout when webhooks lag or fail, so the client can recover
    without waiting on Stripe → webhook delivery.
    """
    caller = _require_signed_in(caller)
    user = _get_or_create_user(db, caller)
    try:
        payload = _sync_user_from_stripe(user, settings)
    except stripe.StripeError as exc:
        logger.exception("Stripe sync failed for %s", user.email)
        raise HTTPException(
            status_code=502,
            detail=str(exc.user_message or exc) or "Could not sync with Stripe",
        ) from exc
    db.commit()
    return payload


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    secrets = settings.stripe_webhook_secret_list
    if not settings.stripe_secret_key or not secrets:
        raise HTTPException(status_code=503, detail="Stripe webhook is not configured")
    stripe.api_key = settings.stripe_secret_key

    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not sig:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    event = _construct_event(payload, sig, secrets)

    etype = event["type"]
    data = _as_dict(event["data"]["object"])

    try:
        if etype == "checkout.session.completed":
            _handle_checkout_completed(db, data, settings)
        elif etype in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "customer.subscription.paused",
            "customer.subscription.resumed",
        }:
            _handle_subscription_event(db, data, settings, etype=etype)
        elif etype in {"invoice.paid", "invoice.payment_succeeded"}:
            _handle_invoice_event(db, data, settings, etype=etype)
        elif etype == "invoice.payment_failed":
            _handle_invoice_event(db, data, settings, etype=etype)
        elif etype == "checkout.session.expired":
            _handle_checkout_expired(db, data)
        else:
            # Still record unknown-but-delivered Stripe events so the admin
            # dashboard / Telegram catch anything we haven't specialized yet.
            # Match on customer id only: user_id metadata and
            # client_reference_id collide with sibling products' user ids.
            user = _user_from_stripe(db, data, by_metadata=False)
            log_event(
                db,
                kind=f"stripe_{etype.replace('.', '_')}",
                email=user.email if user else None,
                message=f"Stripe {etype}"
                + (f" - {user.email}" if user else ""),
                meta={"event": etype, "object_id": data.get("id")},
                debounce_s=0,
            )
        db.commit()
        logger.info("Stripe webhook ok: %s", etype)
    except Exception as exc:
        db.rollback()
        logger.exception("Stripe webhook handler failed for %s", etype)
        notify_signup(
            "webhook_fail",
            f"Stripe webhook handler failed for {etype}: {exc}",
            debounce_key=f"webhook_handler:{etype}",
            debounce_s=300,
        )
        raise

    return {"received": True}


def _user_from_stripe(
    db: Session, obj: object, *, by_metadata: bool = True
) -> User | None:
    data = _as_dict(obj)
    customer_id = data.get("customer")
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")
    if customer_id:
        user = db.scalars(
            select(User).where(User.stripe_customer_id == customer_id)
        ).first()
        if user:
            return user
    if not by_metadata:
        return None

    meta = _as_dict(data.get("metadata"))
    user_id = meta.get("user_id") or data.get("client_reference_id")
    if user_id and str(user_id).isdigit():
        return db.get(User, int(user_id))

    email = (meta.get("email") or data.get("customer_email") or "").strip().lower()
    if email:
        return db.scalars(select(User).where(User.email == email)).first()
    return None


def _handle_checkout_completed(
    db: Session, session: object, settings: Settings
) -> None:
    data = _as_dict(session)
    sub_id = data.get("subscription")
    if isinstance(sub_id, dict):
        sub_id = sub_id.get("id")
    if not sub_id:
        # No subscription means this is not one of our purchases. Do not fall
        # through and bind the customer id: on the shared Stripe account the
        # session may belong to a sibling product whose user id matches ours.
        _skip_foreign(
            "checkout.session.completed (no subscription)", data.get("id"), set()
        )
        return

    sub = stripe.Subscription.retrieve(str(sub_id))
    if not subscription_is_ours(sub, settings):
        _skip_foreign(
            "checkout.session.completed", data.get("id"), _subscription_price_ids(sub)
        )
        return

    user = _user_from_stripe(db, data)
    if user is None:
        logger.warning(
            "checkout.session.completed with no matching user: %s", data.get("id")
        )
        meta = _as_dict(data.get("metadata"))
        email = (
            meta.get("email") or data.get("customer_email") or "(unknown)"
        )
        log_event(
            db,
            kind="stripe_checkout_orphan",
            email=str(email).lower() if email and email != "(unknown)" else None,
            message=(
                f"checkout.session.completed with no matching user "
                f"(session={data.get('id')}, email={email})"
            ),
            debounce_key=f"checkout_orphan:{data.get('id')}",
            debounce_s=0,
        )
        return
    customer = data.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    if customer:
        user.stripe_customer_id = customer
    _apply_subscription(user, sub)
    log_event(
        db,
        kind="stripe_checkout_completed",
        email=user.email,
        message=f"New Pro checkout: {user.email}"
        + (f" (sub={sub_id})" if sub_id else ""),
        meta={"session_id": data.get("id"), "subscription_id": sub_id},
        debounce_key=f"new_sub:{user.email}:{sub_id or data.get('id')}",
        debounce_s=0,
    )


def _handle_subscription_event(
    db: Session,
    sub: object,
    settings: Settings,
    *,
    etype: str = "customer.subscription.updated",
) -> None:
    data = _as_dict(sub)
    if not subscription_is_ours(data, settings):
        _skip_foreign(etype, data.get("id"), _subscription_price_ids(data))
        return
    user = _user_from_stripe(db, data)
    if user is None and data.get("id"):
        user = db.scalars(
            select(User).where(User.stripe_subscription_id == data["id"])
        ).first()
    if user is None:
        logger.warning("subscription event with no matching user: %s", data.get("id"))
        log_event(
            db,
            kind=f"stripe_{etype.replace('.', '_')}",
            message=f"Stripe {etype} with no matching user (sub={data.get('id')})",
            meta={"subscription_id": data.get("id")},
            debounce_s=0,
        )
        return
    prev_status = user.subscription_status or "none"
    customer = data.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    if customer:
        user.stripe_customer_id = customer
    _apply_subscription(user, data)
    status = user.subscription_status or "none"
    kind = {
        "customer.subscription.created": "stripe_subscription_created",
        "customer.subscription.updated": "stripe_subscription_updated",
        "customer.subscription.deleted": "stripe_subscription_canceled",
    }.get(etype, f"stripe_{etype.replace('.', '_')}")
    log_event(
        db,
        kind=kind,
        email=user.email,
        message=(
            f"Stripe {etype.split('.')[-1]}: {user.email} "
            f"{prev_status} → {status}"
        ),
        meta={
            "subscription_id": data.get("id"),
            "status": status,
            "prev_status": prev_status,
        },
        debounce_s=0,
    )


def _invoice_subscription_id(data: dict) -> str | None:
    """Invoices moved the subscription pointer under ``parent`` in 2025-03+."""
    sub_id = _field(data, "subscription")
    if not sub_id:
        parent = _as_dict(data.get("parent"))
        sub_id = _as_dict(parent.get("subscription_details")).get("subscription")
    if isinstance(sub_id, dict):
        sub_id = sub_id.get("id")
    return str(sub_id) if sub_id else None


def _invoice_is_ours(data: dict, sub_id: str | None, settings: Settings) -> bool:
    price_ids = _invoice_price_ids(data)
    if price_ids:
        return is_ours(price_ids, settings)
    # No readable line prices (unusual shape): ask the subscription instead.
    if not sub_id:
        return False
    try:
        return subscription_is_ours(stripe.Subscription.retrieve(sub_id), settings)
    except stripe.StripeError:
        logger.exception("Could not verify ownership of subscription %s", sub_id)
        return False


def _handle_invoice_event(
    db: Session, invoice: object, settings: Settings, *, etype: str
) -> None:
    data = _as_dict(invoice)
    sub_id = _invoice_subscription_id(data)
    if not _invoice_is_ours(data, sub_id, settings):
        _skip_foreign(etype, data.get("id"), _invoice_price_ids(data))
        return
    user = _user_from_stripe(db, data)
    amount = data.get("amount_paid")
    if amount is None:
        amount = data.get("amount_due")
    dollars = None
    try:
        if amount is not None:
            dollars = f"${int(amount) / 100:.2f}"
    except (TypeError, ValueError):
        dollars = None

    if sub_id and etype in {"invoice.paid", "invoice.payment_succeeded"}:
        try:
            sub = stripe.Subscription.retrieve(str(sub_id))
            _handle_subscription_event(
                db, sub, settings, etype="customer.subscription.updated"
            )
        except stripe.StripeError:
            logger.exception("Failed to refresh sub after %s", etype)

    email = user.email if user else (
        (data.get("customer_email") or "").strip().lower() or None
    )
    paid_ok = etype in {"invoice.paid", "invoice.payment_succeeded"}
    kind = "stripe_invoice_paid" if paid_ok else "stripe_invoice_failed"
    log_event(
        db,
        kind=kind,
        email=email,
        message=(
            f"Stripe invoice {'paid' if paid_ok else 'FAILED'}: "
            f"{email or 'unknown'}"
            + (f" ({dollars})" if dollars else "")
        ),
        meta={
            "invoice_id": data.get("id"),
            "subscription_id": sub_id,
            "amount": amount,
        },
        debounce_s=0,
    )


def _handle_checkout_expired(db: Session, session: object) -> None:
    data = _as_dict(session)
    # Metadata user ids collide across the products sharing this Stripe account,
    # so an expired sibling checkout must not be logged against one of our users.
    user = _user_from_stripe(db, data, by_metadata=False)
    meta = _as_dict(data.get("metadata"))
    email = (
        (user.email if user else None)
        or meta.get("email")
        or data.get("customer_email")
        or None
    )
    if isinstance(email, str):
        email = email.strip().lower() or None
    log_event(
        db,
        kind="stripe_checkout_expired",
        email=email,
        message=f"Checkout expired: {email or 'unknown'}",
        meta={"session_id": data.get("id")},
        debounce_s=0,
    )
