"use client";

import Link from "next/link";
import { signIn, useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { BillingResponse, postBilling } from "@/lib/billing";
import { Card } from "@/components/ui";

function safeNextPath(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

function PricingInner() {
  const { data: session, status, update } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const checkout = params.get("checkout");
  const nextPath = safeNextPath(params.get("next"));
  const [busy, setBusy] = useState<"checkout" | "portal" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  // Live Stripe reality (not AUTH_BYPASS / stale JWT). Manage only when this
  // has a customer id — otherwise show Subscribe even if session says "active".
  const [billing, setBilling] = useState<BillingResponse | null>(null);
  const confirmStarted = useRef(false);
  const syncedOnce = useRef(false);

  const refreshBilling = useCallback(async () => {
    if (!session?.accessToken) return null;
    const sync = await postBilling("/billing/sync", session.accessToken);
    setBilling(sync);
    await update();
    return sync;
  }, [session?.accessToken, update]);

  useEffect(() => {
    if (status !== "authenticated" || !session?.accessToken || syncedOnce.current) {
      return;
    }
    syncedOnce.current = true;
    void refreshBilling().catch(() => {
      /* keep session-based UI until the user acts */
    });
  }, [status, session?.accessToken, refreshBilling]);

  useEffect(() => {
    if (checkout === "cancel") {
      setMessage("Checkout canceled — no charge was made.");
      return;
    }
    if (checkout !== "success" || !session?.accessToken) return;
    if (confirmStarted.current) return;
    confirmStarted.current = true;

    let cancelled = false;
    setMessage("Payment received — unlocking Pro…");

    const confirm = async () => {
      try {
        const sync = await refreshBilling();
        if (cancelled) return;
        if (sync?.subscribed) {
          setMessage("You're subscribed — opening the brief…");
          router.replace(nextPath === "/" ? "/brief" : nextPath);
          return;
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not confirm payment");
        }
      }

      for (let tries = 0; tries < 6 && !cancelled; tries += 1) {
        await new Promise((r) => window.setTimeout(r, 1500));
        try {
          const sync = await refreshBilling();
          if (cancelled) return;
          if (sync?.subscribed) {
            setMessage("You're subscribed — opening the brief…");
            router.replace(nextPath === "/" ? "/brief" : nextPath);
            return;
          }
        } catch {
          /* keep trying */
        }
      }

      if (!cancelled) {
        setMessage(null);
        setError(
          "Payment went through, but Pro isn't unlocked yet. Open Account and tap “Sync from Stripe”."
        );
      }
    };

    void confirm();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkout, session?.accessToken, router, nextPath]);

  const startCheckout = useCallback(async () => {
    setError(null);
    const pricingReturn = `/pricing?next=${encodeURIComponent(nextPath)}`;
    if (!session) {
      await signIn("google", { callbackUrl: pricingReturn });
      return;
    }
    setBusy("checkout");
    try {
      const origin = window.location.origin;
      const nextQ = `&next=${encodeURIComponent(nextPath)}`;
      const data = await postBilling("/billing/checkout-session", session.accessToken, {
        success_url: `${origin}/pricing?checkout=success${nextQ}`,
        cancel_url: `${origin}/pricing?checkout=cancel${nextQ}`,
      });
      if (data.already_subscribed) {
        await refreshBilling();
        setMessage("You're already subscribed — opening billing…");
      }
      if (data.url) {
        window.location.href = data.url;
        return;
      }
      throw new Error("No checkout URL returned");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Checkout failed");
      setBusy(null);
    }
  }, [session, nextPath, refreshBilling]);

  const openPortal = useCallback(async () => {
    setError(null);
    if (!session?.accessToken) {
      await signIn("google", {
        callbackUrl: `/pricing?next=${encodeURIComponent(nextPath)}`,
      });
      return;
    }
    setBusy("portal");
    try {
      const data = await postBilling("/billing/portal-session", session.accessToken, {
        return_url: `${window.location.origin}/account`,
      });
      if (data.url) {
        window.location.href = data.url;
        return;
      }
      throw new Error("No portal URL returned");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Portal failed";
      setError(msg);
      // Ghost sandbox subscription cleared — drop Manage and offer Subscribe.
      if (/subscribe first|test mode|no stripe customer/i.test(msg)) {
        setBilling({
          subscribed: false,
          subscription_status: "none",
          stripe_customer_id: null,
          stripe_subscription_id: null,
        });
        setMessage("Sandbox billing cleared — subscribe again with a live card.");
      }
      try {
        await refreshBilling();
      } catch {
        /* keep the local flip above */
      }
      setBusy(null);
    }
  }, [session, nextPath, refreshBilling]);

  // Manage only when Stripe actually has a customer. AUTH_BYPASS / admin can keep
  // session.subscribed true with no live customer — that must not show Manage.
  const showManage = Boolean(billing?.stripe_customer_id);

  return (
    <div className="max-w-xl mx-auto mt-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Pricing</h1>
        <p className="text-sm text-[var(--color-muted)] mt-1">
          Calendar is free — who reports and what the market has priced in. Pro is the
          morning brief: one ranked lean with a real plan, not another data dump.
        </p>
      </div>

      <Card className="p-6 space-y-4">
        <div className="flex items-baseline justify-between gap-4">
          <div>
            <div className="text-lg font-semibold">Pro</div>
            <div className="text-sm text-[var(--color-muted)] mt-1 max-w-xs">
              Each session: the focus, its conviction, and a plan with levels
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-semibold tabular">$9.99</div>
            <div className="text-xs text-[var(--color-muted)]">per month</div>
          </div>
        </div>

        <ul className="text-sm space-y-2 text-[var(--color-muted)]">
          <li>
            <span className="text-white font-medium">Ranked focus + conviction</span> —
            one lean scored 0–100, not a 40-name board
          </li>
          <li>
            <span className="text-white font-medium">A plan</span> — target, window,
            invalidation, and sizing, tied to the sample
          </li>
          <li>
            <span className="text-white font-medium">Honest board read</span> — breadth,
            sample strength, and when it&apos;s a narrow day
          </li>
          <li>
            <span className="text-white font-medium">The whole wave</span> — the driver
            and its correlated peers, flagged so you don&apos;t double up
          </li>
          <li>Full company reaction detail on top of the free calendar</li>
        </ul>

        {status === "authenticated" && (
          <p className="text-xs text-[var(--color-muted)]">
            Signed in as {session?.user?.email}
            {" · "}
            <Link href="/account" className="text-[var(--color-accent)] hover:underline">
              Account
            </Link>
          </p>
        )}

        {message && (
          <p className="text-sm text-[var(--color-up)]">{message}</p>
        )}
        {error && (
          <p className="text-sm text-[var(--color-down)]">{error}</p>
        )}

        {showManage ? (
          <div className="space-y-2">
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void openPortal()}
              className="w-full rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] font-medium py-2.5 hover:bg-[var(--color-panel)] disabled:opacity-60"
            >
              {busy === "portal" ? "Opening…" : "Manage / cancel subscription"}
            </button>
            <p className="text-xs text-[var(--color-muted)] text-center">
              Cancels and card updates happen in Stripe&apos;s billing portal.
            </p>
          </div>
        ) : (
          <button
            type="button"
            disabled={busy !== null || status === "loading"}
            onClick={() => void startCheckout()}
            className="w-full rounded-lg bg-[var(--color-accent)] text-white font-medium py-2.5 hover:opacity-90 disabled:opacity-60"
          >
            {busy === "checkout"
              ? "Redirecting…"
              : session
                ? "Subscribe with Stripe"
                : "Sign in to subscribe"}
          </button>
        )}
      </Card>
    </div>
  );
}

export default function PricingPage() {
  return (
    <Suspense
      fallback={
        <div className="text-sm text-[var(--color-muted)] mt-10 text-center">
          Loading…
        </div>
      }
    >
      <PricingInner />
    </Suspense>
  );
}
