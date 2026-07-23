from __future__ import annotations

import logging
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, OptionalAuth
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db

logger = logging.getLogger("earningsfollower.billing")

router = APIRouter(prefix="/billing", tags=["billing"])


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
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = stripe.Customer.create(
        email=user.email,
        name=user.name or None,
        metadata={"user_id": str(user.id)},
    )
    user.stripe_customer_id = customer["id"]
    return customer["id"]


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
    return {"url": session["url"], "id": session["id"]}


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
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer on this account yet")
    app_url = settings.public_app_url.rstrip("/")
    portal = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=body.return_url or f"{app_url}/pricing",
    )
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
    _stripe(settings)
    user = _get_or_create_user(db, caller)

    customer_id = user.stripe_customer_id
    if not customer_id:
        # Recover customer id from Stripe by email when checkout created one
        # but our row never got the webhook update.
        customers = stripe.Customer.list(email=user.email, limit=1)
        data = list(customers.get("data") or [])
        if data:
            customer_id = data[0]["id"]
            user.stripe_customer_id = customer_id

    if not customer_id:
        db.commit()
        return {
            "subscribed": False,
            "subscription_status": user.subscription_status or "none",
            "synced": False,
        }

    subs = stripe.Subscription.list(customer=customer_id, status="all", limit=10)
    chosen = None
    for sub in list(subs.get("data") or []):
        status = _field(sub, "status")
        if status in {"active", "trialing"}:
            chosen = sub
            break
        if chosen is None:
            chosen = sub

    if chosen is not None:
        _apply_subscription(user, chosen)
    db.commit()

    from app.api.deps import subscription_is_active

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
        "synced": True,
        "stripe_customer_id": user.stripe_customer_id,
        "stripe_subscription_id": user.stripe_subscription_id,
    }


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook is not configured")
    stripe.api_key = settings.stripe_secret_key

    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not sig:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, settings.stripe_webhook_secret
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid payload") from exc
    except stripe.SignatureVerificationError as exc:
        raise HTTPException(status_code=400, detail="Invalid signature") from exc

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
    if customer and not user.stripe_customer_id:
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
    if customer and not user.stripe_customer_id:
        user.stripe_customer_id = customer
    _apply_subscription(user, data)

