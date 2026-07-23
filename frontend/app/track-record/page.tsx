"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, TrackRecordResponse } from "@/lib/api";
import { PaywallBanner, PaywallFade } from "@/components/PaywallBanner";
import { SampleTierBadge } from "@/components/SampleTierBadge";
import { Card, EmptyState, Spinner, Stat } from "@/components/ui";
import { pct } from "@/lib/format";
import { useAuthReady } from "@/lib/useAuthReady";

export default function TrackRecordPage() {
  const { ready, accessToken } = useAuthReady();
  const [data, setData] = useState<TrackRecordResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .trackRecord(accessToken)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ready, accessToken]);

  const isPreview = Boolean(data?.preview);
  const overall = data?.overall;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Track record</h1>
        <p className="text-sm text-[var(--color-muted)] mt-1 max-w-2xl">
          Aggregated paper-research outcomes with sample sizes and win-rate floors.
          Historical journal stats — not a promise of future results.
        </p>
      </div>

      {isPreview ? (
        <PaywallBanner
          title="Track record — preview"
          note={data?.preview_note}
        />
      ) : null}

      {!ready || loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState title="Couldn't load track record." hint="Is the backend running?" />
      ) : !overall || overall.closed_count === 0 ? (
        <EmptyState
          title="No closed paper trades yet."
          hint="The scorecard fills in as the paper journal closes simulated trades."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <Stat label="Closed trades" value={String(overall.closed_count)} />
            <Stat
              label="Win rate"
              value={pct(overall.win_rate, 0)}
              sub={
                overall.win_rate_ci_low != null
                  ? `Wilson low ${pct(overall.win_rate_ci_low, 0)}`
                  : undefined
              }
              blur={isPreview}
            />
            <Stat
              label="Sample"
              value={<SampleTierBadge tier={overall.sample_tier} />}
            />
            <Stat
              label="Total P&L"
              value={
                overall.total_pnl != null
                  ? `$${overall.total_pnl.toFixed(0)}`
                  : "—"
              }
              sub={
                overall.avg_pnl != null
                  ? `avg $${overall.avg_pnl.toFixed(0)}`
                  : isPreview
                    ? "Pro unlocks P&L"
                    : undefined
              }
              blur={isPreview}
            />
          </div>

          <Card className="p-4">
            <h2 className="font-semibold mb-3">By strategy</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[var(--color-muted)] text-[11px] uppercase tracking-wide">
                    <th className="py-1.5 pr-3">Strategy</th>
                    <th className="py-1.5 pr-3">n</th>
                    <th className="py-1.5 pr-3">Win</th>
                    <th className="py-1.5 pr-3">Sample</th>
                    <th className="py-1.5 pr-0">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.by_strategy.map((row) => (
                    <tr key={row.key} className="border-t border-[var(--color-edge)]">
                      <td className="py-2 pr-3 font-semibold capitalize">{row.key}</td>
                      <td className="py-2 pr-3">{row.n}</td>
                      <td className="py-2 pr-3">
                        {pct(row.win_rate, 0)}
                        {row.win_rate_ci_low != null ? (
                          <span className="text-[10px] text-[var(--color-muted)]">
                            {" "}
                            (≥{pct(row.win_rate_ci_low, 0)})
                          </span>
                        ) : null}
                      </td>
                      <td className="py-2 pr-3">
                        <SampleTierBadge tier={row.sample_tier} />
                      </td>
                      <td className="py-2 pr-0">
                        {row.total_pnl != null ? `$${row.total_pnl.toFixed(0)}` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data?.window_note ? (
              <p className="text-xs text-[var(--color-muted)] mt-3">{data.window_note}</p>
            ) : null}
          </Card>

          {isPreview ? (
            <PaywallFade label="Unlock full strategy P&L breakdown with Pro" />
          ) : (
            <p className="text-xs text-[var(--color-muted)] mt-4">
              Want the live book?{" "}
              <Link href="/paper" className="text-[var(--color-accent)] hover:underline">
                Paper
              </Link>{" "}
              stays admin-only.
            </p>
          )}
        </>
      )}
    </div>
  );
}
