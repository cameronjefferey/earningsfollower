"use client";

import Link from "next/link";
import { signIn, useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { postBilling } from "@/lib/billing";
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

  useEffect(() => {
    if (checkout === "success") {
      setMessage("Payment received — refreshing your subscription status…");
      let tries = 0;
      const refresh = async () => {
        const next = await update();
        if (next?.subscribed) {
          setMessage("You're subscribed — taking you back…");
          router.replace(nextPath);
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
  }, [checkout, update, router, nextPath]);

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
      if (data.url) {
        window.location.href = data.url;
        return;
      }
      throw new Error("No checkout URL returned");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Checkout failed");
      setBusy(null);
    }
  }, [session, nextPath]);

  const openPortal = useCallback(async () => {
    setError(null);
    const pricingReturn = `/pricing?next=${encodeURIComponent(nextPath)}`;
    if (!session?.accessToken) {
      await signIn("google", { callbackUrl: pricingReturn });
      return;
    }
    setBusy("portal");
    try {
      const data = await postBilling("/billing/portal-session", session.accessToken, {
        return_url: `${window.location.origin}${pricingReturn}`,
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
  }, [session, nextPath]);

  const subscribed = Boolean(session?.subscribed);

  return (
    <div className="max-w-xl mx-auto mt-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Pricing</h1>
        <p className="text-sm text-[var(--color-muted)] mt-1">
          Calendar is free — who reports and what the market has priced in. Pro is
          for traders who want a single daily lean, not another data dump.
        </p>
      </div>

      <Card className="p-6 space-y-4">
        <div className="flex items-baseline justify-between gap-4">
          <div>
            <div className="text-lg font-semibold">Pro</div>
            <div className="text-sm text-[var(--color-muted)] mt-1 max-w-xs">
              Each session: one focus setup, what to watch, and when to drop it
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-semibold tabular">$9.99</div>
            <div className="text-xs text-[var(--color-muted)]">per month</div>
          </div>
        </div>

        <ul className="text-sm space-y-2 text-[var(--color-muted)]">
          <li>
            <span className="text-white font-medium">Morning brief</span> — ranked
            focus instead of scrolling Waves/Drift yourself
          </li>
          <li>
            <span className="text-white font-medium">Action / watch / drop-if</span>{" "}
            — so you know the lean and the kill switch
          </li>
          <li>
            <span className="text-white font-medium">Sample honesty</span> — n, win
            rate, thin-history labels
          </li>
          <li>Full company reaction detail on top of the free calendar</li>
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
