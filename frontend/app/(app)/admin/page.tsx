"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/api";
import { Card, EmptyState, Spinner, Stat } from "@/components/ui";
import { useAuthReady } from "@/lib/useAuthReady";

type AdminTraffic = {
  generated_at: string;
  days: number;
  by_kind: Record<string, number>;
  daily: Record<string, Record<string, number>>;
  unique_sessions: number;
  sessions_with_pageviews: number;
  multi_page_sessions: number;
  avg_pages_per_session: number;
  top_paths: Array<{ path: string; views: number; sessions: number }>;
  top_tickers: Array<{ ticker: string; views: number }>;
  cta_clicks: Array<{ target: string; clicks: number }>;
  viewers: Record<string, number>;
  referrers: Array<{ referrer: string; count: number }>;
};

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
  if (!iso) return "-";
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
  const [traffic, setTraffic] = useState<AdminTraffic | null>(null);
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
        const headers = { Authorization: `Bearer ${accessToken}` };
        const [res, trafficRes] = await Promise.all([
          fetch(`${API_BASE}/admin/overview`, { headers, cache: "no-store" }),
          fetch(`${API_BASE}/admin/traffic?days=7`, { headers, cache: "no-store" }),
        ]);
        if (!res.ok) {
          throw new Error(`Could not load admin overview (${res.status})`);
        }
        const json = (await res.json()) as AdminOverview;
        if (!cancelled) setData(json);
        if (trafficRes.ok) {
          const t = (await trafficRes.json()) as AdminTraffic;
          if (!cancelled) setTraffic(t);
        }
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

      {traffic ? (
        <div className="space-y-6">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">
              Traffic - last {traffic.days} days
            </h2>
            <p className="text-sm text-[var(--color-muted)] mt-0.5">
              What visitors are doing on the site (admin sessions excluded).
            </p>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat
              label="Sessions"
              value={String(traffic.unique_sessions)}
            />
            <Stat
              label="Pageviews"
              value={String(traffic.by_kind.pageview ?? 0)}
            />
            <Stat
              label="Pages / session"
              value={String(traffic.avg_pages_per_session)}
            />
            <Stat
              label="Multi-page sessions"
              value={String(traffic.multi_page_sessions)}
            />
          </div>

          <Card className="p-5">
            <div className="text-sm font-medium mb-3">Funnel (7d)</div>
            <div className="flex flex-wrap gap-2 text-xs">
              {[
                ["ad_landing", "Ad landings"],
                ["ad_engage", "Engaged"],
                ["cta_click", "CTA clicks"],
                ["calendar_view", "Calendar views"],
                ["company_view", "Company views"],
                ["guest_gate", "Gate hits"],
                ["signup", "Signups"],
              ].map(([k, label]) => (
                <span
                  key={k}
                  className="rounded-md px-2.5 py-1 bg-[var(--color-panel-2)] border border-[var(--color-edge)]"
                >
                  {label}:{" "}
                  <span className="tabular font-medium text-white">
                    {traffic.by_kind[k] ?? 0}
                  </span>
                </span>
              ))}
              {Object.entries(traffic.viewers).map(([v, n]) => (
                <span
                  key={v}
                  className="rounded-md px-2.5 py-1 bg-[var(--color-panel-2)] border border-[var(--color-edge)] text-[var(--color-muted)]"
                >
                  {v} views: <span className="tabular">{n}</span>
                </span>
              ))}
            </div>
          </Card>

          <div className="grid lg:grid-cols-3 gap-6">
            <Card className="p-5 overflow-hidden lg:col-span-1">
              <div className="text-sm font-medium mb-3">Top pages</div>
              <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1 text-sm">
                {traffic.top_paths.map((p) => (
                  <div
                    key={p.path}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="truncate text-[var(--color-muted)]">
                      {p.path}
                    </span>
                    <span className="shrink-0 tabular text-white">
                      {p.views}
                      <span className="text-[var(--color-muted)] text-xs">
                        {" "}
                        · {p.sessions}s
                      </span>
                    </span>
                  </div>
                ))}
                {!traffic.top_paths.length ? (
                  <p className="text-[var(--color-muted)]">
                    No pageviews yet - data starts with the next deploy.
                  </p>
                ) : null}
              </div>
            </Card>

            <Card className="p-5 overflow-hidden lg:col-span-1">
              <div className="text-sm font-medium mb-3">Top tickers opened</div>
              <div className="flex flex-wrap gap-2 text-xs">
                {traffic.top_tickers.map((t) => (
                  <span
                    key={t.ticker}
                    className="rounded-md px-2.5 py-1 bg-[var(--color-panel-2)] border border-[var(--color-edge)]"
                  >
                    {t.ticker} <span className="tabular text-white">{t.views}</span>
                  </span>
                ))}
                {!traffic.top_tickers.length ? (
                  <p className="text-sm text-[var(--color-muted)]">
                    No company views yet.
                  </p>
                ) : null}
              </div>
            </Card>

            <Card className="p-5 overflow-hidden lg:col-span-1">
              <div className="text-sm font-medium mb-3">CTA clicks by placement</div>
              <div className="space-y-1.5 text-sm">
                {traffic.cta_clicks.map((c) => (
                  <div
                    key={c.target}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="truncate text-[var(--color-muted)]">
                      {c.target.replace(/_/g, " ")}
                    </span>
                    <span className="shrink-0 tabular text-white">{c.clicks}</span>
                  </div>
                ))}
                {!traffic.cta_clicks.length ? (
                  <p className="text-[var(--color-muted)]">No CTA clicks yet.</p>
                ) : null}
              </div>
              {traffic.referrers.length ? (
                <>
                  <div className="text-sm font-medium mt-5 mb-2">Referrers</div>
                  <div className="space-y-1 text-xs text-[var(--color-muted)]">
                    {traffic.referrers.map((r) => (
                      <div
                        key={r.referrer}
                        className="flex items-center justify-between gap-2"
                      >
                        <span className="truncate">{r.referrer}</span>
                        <span className="shrink-0 tabular text-white">{r.count}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : null}
            </Card>
          </div>
        </div>
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
                No events yet - new signups and Stripe webhooks will show here.
              </p>
            ) : null}
          </div>
        </Card>
      </div>
    </div>
  );
}
