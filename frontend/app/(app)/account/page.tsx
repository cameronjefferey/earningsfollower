"use client";

import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
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

type AccountProfile = {
  subscribed: boolean;
  subscriptionStatus: string;
  isAdmin: boolean;
  periodEnd: string | null;
  waveAlerts: boolean;
};

function formatPeriodEnd(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function AccountPage() {
  const { data: session, status, update } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [profile, setProfile] = useState<AccountProfile | null>(null);
  const syncedForToken = useRef<string | null>(null);

  const refreshProfile = useCallback(
    async (opts?: { fromStripe?: boolean }) => {
      if (!session?.accessToken) return;
      setRefreshing(true);
      setError(null);
      setNote(null);
      try {
        if (opts?.fromStripe) {
          const sync = await postBilling("/billing/sync", session.accessToken);
          setProfile((prev) => ({
            subscribed: Boolean(sync.subscribed),
            subscriptionStatus: sync.subscription_status || "none",
            isAdmin: Boolean(session.isAdmin),
            periodEnd: sync.current_period_end ?? null,
            waveAlerts: prev?.waveAlerts ?? true,
          }));
          await update();
          setNote(
            sync.subscribed
              ? "Synced with Stripe - Pro is active."
              : "Synced with Stripe - no active subscription on this account."
          );
          return;
        }

        const res = await fetch(`${API_BASE}/auth/me`, {
          headers: { Authorization: `Bearer ${session.accessToken}` },
          cache: "no-store",
        });
        if (!res.ok) {
          throw new Error(`Could not load account (${res.status})`);
        }
        const data = (await res.json()) as {
          subscribed: boolean;
          subscription_status: string;
          is_admin: boolean;
          current_period_end?: string | null;
          wave_alerts?: boolean;
        };
        setProfile({
          subscribed: Boolean(data.subscribed),
          subscriptionStatus: data.subscription_status || "none",
          isAdmin: Boolean(data.is_admin),
          periodEnd: data.current_period_end ?? null,
          waveAlerts: data.wave_alerts !== false,
        });
        // If DB still says free, pull from Stripe once - covers webhook misses.
        if (!data.subscribed) {
          const sync = await postBilling("/billing/sync", session.accessToken);
          setProfile({
            subscribed: Boolean(sync.subscribed),
            subscriptionStatus: sync.subscription_status || "none",
            isAdmin: Boolean(data.is_admin),
            periodEnd: sync.current_period_end ?? null,
            waveAlerts: data.wave_alerts !== false,
          });
        }
        await update();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not load account");
      } finally {
        setRefreshing(false);
      }
    },
    [session?.accessToken, session?.isAdmin, update]
  );

  useEffect(() => {
    if (status !== "authenticated" || !session?.accessToken) return;
    if (syncedForToken.current === session.accessToken) return;
    syncedForToken.current = session.accessToken;
    void refreshProfile();
  }, [status, session?.accessToken, refreshProfile]);

  const toggleWaveAlerts = useCallback(
    async (next: boolean) => {
      if (!session?.accessToken) return;
      setProfile((prev) => (prev ? { ...prev, waveAlerts: next } : prev));
      try {
        const res = await fetch(`${API_BASE}/auth/prefs`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${session.accessToken}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ wave_alerts: next }),
        });
        if (!res.ok) throw new Error(`Could not save (${res.status})`);
      } catch (e) {
        setProfile((prev) => (prev ? { ...prev, waveAlerts: !next } : prev));
        setError(e instanceof Error ? e.message : "Could not save preference");
      }
    },
    [session?.accessToken]
  );

  const openPortal = useCallback(async () => {
    setError(null);
    setNote(null);
    if (!session?.accessToken) {
      window.location.href = "/login?next=/account";
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
              Sign in to manage your subscription.
            </p>
          </div>
          <Link
            href="/login?next=/account"
            className="block w-full text-center rounded-lg bg-[var(--color-accent)] text-white font-medium py-2.5 hover:opacity-90"
          >
            Sign in
          </Link>
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

  const subscribed = profile?.subscribed ?? Boolean(session.subscribed);
  const subStatus =
    profile?.subscriptionStatus ?? session.subscriptionStatus ?? "none";
  const isAdmin = profile?.isAdmin ?? Boolean(session.isAdmin);
  const periodEnd = formatPeriodEnd(profile?.periodEnd);

  return (
    <div className="max-w-lg mx-auto mt-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Account</h1>
        <p className="text-sm text-[var(--color-muted)] mt-1">
          Profile, Pro status, and cancel/update billing.
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
              {isAdmin ? (
                <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium border text-[var(--color-accent)] border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10">
                  Admin access
                </span>
              ) : null}
            </div>
            <div className="text-sm text-[var(--color-muted)] truncate">
              {session.user?.email}
            </div>
            <div className="text-xs text-[var(--color-muted)] mt-1">
              <Link href="/login/forgot" className="hover:text-white">
                Set or reset password
              </Link>
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
                ? periodEnd
                  ? `Pro is on through ${periodEnd}. Cancel anytime in Stripe billing.`
                  : "Pro is on. Cancel anytime in Stripe billing."
                : "Paid but still showing Free? Sync from Stripe. Otherwise upgrade on Pricing."}
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

        {note && <p className="text-sm text-[var(--color-up)]">{note}</p>}
        {error && <p className="text-sm text-[var(--color-down)]">{error}</p>}

        <div className="flex flex-col sm:flex-row gap-2">
          {subscribed ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void openPortal()}
              className="flex-1 rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] font-medium py-2.5 hover:bg-[var(--color-panel)] disabled:opacity-60"
            >
              {busy ? "Opening…" : "Manage / cancel"}
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
            disabled={refreshing}
            onClick={() => {
              void refreshProfile({ fromStripe: true });
            }}
            className="rounded-lg border border-[var(--color-edge)] px-4 py-2.5 text-sm text-[var(--color-muted)] hover:text-white hover:bg-[var(--color-panel-2)] disabled:opacity-60"
          >
            {refreshing ? "Syncing…" : "Sync from Stripe"}
          </button>
        </div>
      </Card>

      <Card className="p-6 space-y-3">
        <div className="text-sm text-[var(--color-muted)]">Email alerts</div>
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={profile?.waveAlerts ?? true}
            onChange={(e) => void toggleWaveAlerts(e.target.checked)}
            className="mt-1 accent-[var(--color-accent)]"
          />
          <span>
            <span className="block font-medium">Wave alerts</span>
            <span className="block text-sm text-[var(--color-muted)] mt-0.5">
              Email me when a new wave forms: peers just reported and a name in
              the group reports soon.
              {subscribed
                ? ""
                : " Alerts send while Pro is active."}
            </span>
          </span>
        </label>
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
