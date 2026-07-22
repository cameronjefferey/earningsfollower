"use client";

import Link from "next/link";
import { signIn, useSession } from "next-auth/react";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { postBilling } from "@/lib/billing";
import { Card } from "@/components/ui";

function PricingInner() {
  const { data: session, status, update } = useSession();
  const params = useSearchParams();
  const checkout = params.get("checkout");
  const [busy, setBusy] = useState<"checkout" | "portal" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (checkout === "success") {
      setMessage("Payment received — refreshing your subscription status…");
      let tries = 0;
      const refresh = async () => {
        const next = await update();
        if (next?.subscribed) {
          setMessage("You're subscribed. Paid pages are unlocked.");
          return;
        }
        tries += 1;
        if (tries < 6) {
          window.setTimeout(() => {
            void refresh();
          }, 1500);
          return;
        }
        setMessage(
          "Payment received, but subscription status hasn't updated yet. Refresh the page in a few seconds."
        );
      };
      void refresh();
    } else if (checkout === "cancel") {
      setMessage("Checkout canceled — no charge was made.");
    }
  }, [checkout, update]);

  const startCheckout = useCallback(async () => {
    setError(null);
    if (!session) {
      await signIn("google", { callbackUrl: "/pricing" });
      return;
    }
    setBusy("checkout");
    try {
      const origin = window.location.origin;
      const data = await postBilling("/billing/checkout-session", session.accessToken, {
        success_url: `${origin}/pricing?checkout=success`,
        cancel_url: `${origin}/pricing?checkout=cancel`,
      });
      if (data.url) {
        window.location.href = data.url;
        return;
      }
      throw new Error("No checkout URL returned");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Checkout failed");
      setBusy(null);
    }
  }, [session]);

  const openPortal = useCallback(async () => {
    setError(null);
    if (!session?.accessToken) {
      await signIn("google", { callbackUrl: "/pricing" });
      return;
    }
    setBusy("portal");
    try {
      const data = await postBilling("/billing/portal-session", session.accessToken, {
        return_url: `${window.location.origin}/pricing`,
      });
      if (data.url) {
        window.location.href = data.url;
        return;
      }
      throw new Error("No portal URL returned");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Portal failed");
      setBusy(null);
    }
  }, [session]);

  const subscribed = Boolean(session?.subscribed);

  return (
    <div className="max-w-xl mx-auto mt-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Pricing</h1>
        <p className="text-sm text-[var(--color-muted)] mt-1">
          Calendar is free. Waves, Drift, Reddit, and company research unlock
          with a monthly subscription. Trade plans and paper tools stay private.
        </p>
      </div>

      <Card className="p-6 space-y-4">
        <div className="flex items-baseline justify-between gap-4">
          <div>
            <div className="text-lg font-semibold">Pro</div>
            <div className="text-sm text-[var(--color-muted)]">
              Full earnings research around the calendar
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-semibold">Monthly</div>
            <div className="text-xs text-[var(--color-muted)]">
              Price set in Stripe
            </div>
          </div>
        </div>

        <ul className="text-sm space-y-1.5 text-[var(--color-muted)]">
          <li>• Peer waves & PEAD drift research</li>
          <li>• Reddit attention signals</li>
          <li>• Company reaction history & implied-move detail</li>
        </ul>

        {status === "authenticated" && (
          <p className="text-xs text-[var(--color-muted)]">
            Signed in as {session?.user?.email}
            {subscribed
              ? ` · status: ${session?.subscriptionStatus ?? "active"}`
              : " · not subscribed"}
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

        {subscribed ? (
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void openPortal()}
            className="w-full rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] font-medium py-2.5 hover:bg-[var(--color-panel)] disabled:opacity-60"
          >
            {busy === "portal" ? "Opening…" : "Manage subscription"}
          </button>
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
