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

logger = logging.getLogger("earningsfollower.billing")

router = APIRouter(prefix="/billing", tags=["billing"])

_ACTIVE = frozenset({"active", "trialing"})


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
        # DB but 404 in the API — clear them so the user can re-subscribe cleanly.
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


def _pick_subscription(customer_id: str) -> object | None:
    subs = _list_data(
        stripe.Subscription.list(customer=customer_id, status="all", limit=10)
    )
    chosen = None
    for sub in subs:
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

    chosen = _pick_subscription(customer_id)
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
        # If they already paid, don't start a second subscription — send portal.
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
            metadata={"user_id": str(user.id), "email": user.email},
            allow_promotion_codes=True,
        )
    except stripe.InvalidRequestError as exc:
        logger.exception("Stripe checkout invalid request")
        raise HTTPException(
            status_code=400,
            detail=str(exc.user_message or exc) or "Stripe rejected checkout",
        ) from exc
    except stripe.StripeError as exc:
        logger.exception("Stripe checkout failed")
        raise HTTPException(
            status_code=502,
            detail=str(exc.user_message or exc) or "Stripe checkout failed",
        ) from exc
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
                detail="No Stripe customer on this account yet — subscribe first",
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
            _handle_checkout_completed(db, data)
        elif etype in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            _handle_subscription_event(db, data)
        elif etype in {"invoice.paid", "invoice.payment_succeeded"}:
            # Keep status fresh after renewals.
            sub_id = _field(data, "subscription")
            if isinstance(sub_id, dict):
                sub_id = sub_id.get("id")
            if sub_id:
                sub = stripe.Subscription.retrieve(str(sub_id))
                _handle_subscription_event(db, sub)
        db.commit()
        logger.info("Stripe webhook ok: %s", etype)
    except Exception:
        db.rollback()
        logger.exception("Stripe webhook handler failed for %s", etype)
        raise

    return {"received": True}


def _user_from_stripe(db: Session, obj: object) -> User | None:
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

    meta = _as_dict(data.get("metadata"))
    user_id = meta.get("user_id") or data.get("client_reference_id")
    if user_id and str(user_id).isdigit():
        return db.get(User, int(user_id))

    email = (meta.get("email") or data.get("customer_email") or "").strip().lower()
    if email:
        return db.scalars(select(User).where(User.email == email)).first()
    return None


def _handle_checkout_completed(db: Session, session: object) -> None:
    data = _as_dict(session)
    user = _user_from_stripe(db, data)
    if user is None:
        logger.warning(
            "checkout.session.completed with no matching user: %s", data.get("id")
        )
        return
    customer = data.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    if customer:
        user.stripe_customer_id = customer
    sub_id = data.get("subscription")
    if isinstance(sub_id, dict):
        sub_id = sub_id.get("id")
    if sub_id:
        sub = stripe.Subscription.retrieve(str(sub_id))
        _apply_subscription(user, sub)


def _handle_subscription_event(db: Session, sub: object) -> None:
    data = _as_dict(sub)
    user = _user_from_stripe(db, data)
    if user is None and data.get("id"):
        user = db.scalars(
            select(User).where(User.stripe_subscription_id == data["id"])
        ).first()
    if user is None:
        logger.warning("subscription event with no matching user: %s", data.get("id"))
        return
    customer = data.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    if customer:
        user.stripe_customer_id = customer
    _apply_subscription(user, data)
