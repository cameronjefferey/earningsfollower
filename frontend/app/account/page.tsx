"use client";

import Link from "next/link";
import { signIn, signOut, useSession } from "next-auth/react";
import { useCallback, useEffect, useState } from "react";
import { postBilling } from "@/lib/billing";
import { Card } from "@/components/ui";

function statusLabel(status: string | undefined, subscribed: boolean): string {
  if (subscribed) {
    if (status === "trialing") return "Trialing";
    return "Active";
  }
  if (!status || status === "none") return "Not subscribed";
  return status.replace(/_/g, " ");
}

export default function AccountPage() {
  const { data: session, status, update } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (status === "authenticated") {
      setRefreshing(true);
      void update()
        .catch(() => undefined)
        .finally(() => setRefreshing(false));
    }
  }, [status, update]);

  const openPortal = useCallback(async () => {
    setError(null);
    if (!session?.accessToken) {
      await signIn("google", { callbackUrl: "/account" });
      return;
    }
    setBusy(true);
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
      setError(e instanceof Error ? e.message : "Could not open billing portal");
      setBusy(false);
    }
  }, [session]);

  if (status === "loading") {
    return (
      <div className="text-sm text-[var(--color-muted)] mt-10 text-center">
        Loading account…
      </div>
    );
  }

  if (!session) {
    return (
      <div className="max-w-md mx-auto mt-10">
        <Card className="p-6 space-y-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Account</h1>
            <p className="text-sm text-[var(--color-muted)] mt-1">
              Sign in with Google to manage your subscription.
            </p>
          </div>
          <button
            type="button"
            onClick={() => signIn("google", { callbackUrl: "/account" })}
            className="w-full rounded-lg bg-[var(--color-accent)] text-white font-medium py-2.5 hover:opacity-90"
          >
            Continue with Google
          </button>
          <p className="text-xs text-[var(--color-muted)]">
            New here? See{" "}
            <Link href="/pricing" className="text-[var(--color-accent)] hover:underline">
              pricing
            </Link>
            .
          </p>
        </Card>
      </div>
    );
  }

  const subscribed = Boolean(session.subscribed);
  const subStatus = session.subscriptionStatus ?? "none";

  return (
    <div className="max-w-lg mx-auto mt-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Account</h1>
        <p className="text-sm text-[var(--color-muted)] mt-1">
          Profile and billing for your earningsfollower access.
        </p>
      </div>

      <Card className="p-6 space-y-4">
        <div className="flex items-center gap-3">
          {session.user?.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={session.user.image}
              alt=""
              className="h-12 w-12 rounded-full border border-[var(--color-edge)]"
              referrerPolicy="no-referrer"
            />
          ) : (
            <div className="h-12 w-12 rounded-full bg-[var(--color-panel-2)] border border-[var(--color-edge)] flex items-center justify-center text-lg font-medium">
              {(session.user?.email?.[0] || "?").toUpperCase()}
            </div>
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="font-medium truncate">
                {session.user?.name || "Signed in"}
              </div>
              {session.isAdmin ? (
                <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium border text-[var(--color-accent)] border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10">
                  Admin access
                </span>
              ) : null}
            </div>
            <div className="text-sm text-[var(--color-muted)] truncate">
              {session.user?.email}
            </div>
          </div>
        </div>
      </Card>

      <Card className="p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-sm text-[var(--color-muted)]">Subscription</div>
            <div className="text-lg font-semibold mt-0.5">
              {statusLabel(subStatus, subscribed)}
              {refreshing ? (
                <span className="text-xs font-normal text-[var(--color-muted)] ml-2">
                  updating…
                </span>
              ) : null}
            </div>
            <p className="text-sm text-[var(--color-muted)] mt-1">
              {subscribed
                ? "Pro unlocks Waves, Drift, Reddit, and company research. Paper, Learning, and trade plans stay admin-only."
                : "Calendar stays free. Upgrade to unlock research views."}
            </p>
          </div>
          <span
            className={`shrink-0 mt-1 inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium border ${
              subscribed
                ? "text-[var(--color-up)] border-[var(--color-up)]/40 bg-[var(--color-up)]/10"
                : "text-[var(--color-muted)] border-[var(--color-edge)] bg-[var(--color-panel-2)]"
            }`}
          >
            {subscribed ? "Pro" : "Free"}
          </span>
        </div>

        {error && <p className="text-sm text-[var(--color-down)]">{error}</p>}

        <div className="flex flex-col sm:flex-row gap-2">
          {subscribed ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void openPortal()}
              className="flex-1 rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] font-medium py-2.5 hover:bg-[var(--color-panel)] disabled:opacity-60"
            >
              {busy ? "Opening…" : "Manage billing"}
            </button>
          ) : (
            <Link
              href="/pricing"
              className="flex-1 text-center rounded-lg bg-[var(--color-accent)] text-white font-medium py-2.5 hover:opacity-90"
            >
              View pricing
            </Link>
          )}
          <button
            type="button"
            onClick={() => void update()}
            className="rounded-lg border border-[var(--color-edge)] px-4 py-2.5 text-sm text-[var(--color-muted)] hover:text-white hover:bg-[var(--color-panel-2)]"
          >
            Refresh status
          </button>
        </div>
      </Card>

      <Card className="p-6 space-y-3">
        <div className="text-sm text-[var(--color-muted)]">Session</div>
        <button
          type="button"
          onClick={() => signOut({ callbackUrl: "/" })}
          className="w-full rounded-lg border border-[var(--color-edge)] font-medium py-2.5 text-[var(--color-down)] hover:bg-[var(--color-down)]/10"
        >
          Sign out
        </button>
      </Card>
    </div>
  );
}
