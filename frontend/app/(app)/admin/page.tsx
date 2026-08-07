"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/api";
import { Card, EmptyState, Spinner, Stat } from "@/components/ui";
import { useAuthReady } from "@/lib/useAuthReady";

type AdminOverview = {
  generated_at: string;
  users: {
    total: number;
    subscribed: number;
    created_7d: number;
    created_30d: number;
    by_status: Record<string, number>;
  };
  recent_users: Array<{
    id: number;
    email: string;
    name: string | null;
    subscription_status: string;
    subscribed: boolean;
    has_password: boolean;
    has_google: boolean;
    email_verified: boolean;
    stripe_customer_id: string | null;
    created_at: string | null;
    current_period_end: string | null;
  }>;
  recent_events: Array<{
    id: number;
    kind: string;
    email: string | null;
    message: string;
    created_at: string | null;
  }>;
};

function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function AdminPage() {
  const { ready, accessToken, isAdmin } = useAuthReady();
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ready) return;
    if (!isAdmin || !accessToken) {
      setLoading(false);
      setError("Admin access required.");
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}/admin/overview`, {
          headers: { Authorization: `Bearer ${accessToken}` },
          cache: "no-store",
        });
        if (!res.ok) {
          throw new Error(`Could not load admin overview (${res.status})`);
        }
        const json = (await res.json()) as AdminOverview;
        if (!cancelled) setData(json);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, isAdmin, accessToken]);

  if (!ready || loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  if (error || !data) {
    return (
      <EmptyState
        title="Admin only"
        hint={error || "Sign in with an admin account."}
      />
    );
  }

  const statusEntries = Object.entries(data.users.by_status);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Ops</h1>
          <p className="text-sm text-[var(--color-muted)] mt-1">
            Signups, subscriptions, and site activity. Updated{" "}
            {fmtWhen(data.generated_at)}.
          </p>
        </div>
        <Link
          href="/account"
          className="text-sm text-[var(--color-muted)] hover:text-white"
        >
          Account →
        </Link>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Users" value={String(data.users.total)} />
        <Stat label="Subscribed" value={String(data.users.subscribed)} />
        <Stat label="New (7d)" value={String(data.users.created_7d)} />
        <Stat label="New (30d)" value={String(data.users.created_30d)} />
      </div>

      {statusEntries.length ? (
        <Card className="p-5">
          <div className="text-sm font-medium mb-3">Subscription status</div>
          <div className="flex flex-wrap gap-2">
            {statusEntries.map(([status, n]) => (
              <span
                key={status}
                className="text-xs rounded-md px-2.5 py-1 bg-[var(--color-panel-2)] border border-[var(--color-edge)]"
              >
                {status}: <span className="tabular font-medium">{n}</span>
              </span>
            ))}
          </div>
        </Card>
      ) : null}

      <div className="grid lg:grid-cols-2 gap-6">
        <Card className="p-5 overflow-hidden">
          <div className="text-sm font-medium mb-4">Recent accounts</div>
          <div className="space-y-3 max-h-[28rem] overflow-y-auto pr-1">
            {data.recent_users.map((u) => (
              <div
                key={u.id}
                className="flex items-start justify-between gap-3 text-sm border-b border-[var(--color-edge)]/60 pb-3 last:border-0"
              >
                <div className="min-w-0">
                  <div className="font-medium truncate">{u.email}</div>
                  <div className="text-xs text-[var(--color-muted)] mt-0.5">
                    {fmtWhen(u.created_at)}
                    {u.has_google ? " · Google" : ""}
                    {u.has_password ? " · Password" : ""}
                  </div>
                </div>
                <span
                  className={`shrink-0 text-[11px] uppercase tracking-wide rounded px-1.5 py-0.5 ${
                    u.subscribed
                      ? "bg-[var(--color-up)]/15 text-[var(--color-up)]"
                      : "bg-[var(--color-panel-2)] text-[var(--color-muted)]"
                  }`}
                >
                  {u.subscription_status}
                </span>
              </div>
            ))}
            {!data.recent_users.length ? (
              <p className="text-sm text-[var(--color-muted)]">No users yet.</p>
            ) : null}
          </div>
        </Card>

        <Card className="p-5 overflow-hidden">
          <div className="text-sm font-medium mb-4">Activity feed</div>
          <div className="space-y-3 max-h-[28rem] overflow-y-auto pr-1">
            {data.recent_events.map((e) => (
              <div
                key={e.id}
                className="text-sm border-b border-[var(--color-edge)]/60 pb-3 last:border-0"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] uppercase tracking-wide text-[var(--color-accent)]">
                    {e.kind.replace(/_/g, " ")}
                  </span>
                  <span className="text-xs text-[var(--color-muted)] tabular">
                    {fmtWhen(e.created_at)}
                  </span>
                </div>
                <p className="mt-1 text-[var(--color-muted)] leading-snug">
                  {e.message}
                </p>
              </div>
            ))}
            {!data.recent_events.length ? (
              <p className="text-sm text-[var(--color-muted)]">
                No events yet — new signups and Stripe webhooks will show here.
              </p>
            ) : null}
          </div>
        </Card>
      </div>
    </div>
  );
}
