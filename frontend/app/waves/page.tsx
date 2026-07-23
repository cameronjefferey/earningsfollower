"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ThemeTag, WaveSignal, WavesResponse } from "@/lib/api";
import { BlurValue } from "@/components/BlurValue";
import { PaywallBanner, PaywallFade } from "@/components/PaywallBanner";
import { Card, EmptyState, Spinner, ThemePill } from "@/components/ui";
import { InfoTip } from "@/components/InfoTip";
import { glossary } from "@/lib/glossary";
import { fmtDate, moveClass, pct, signedPct } from "@/lib/format";

interface TargetGroup {
  target: string;
  targetName: string | null;
  targetReportDate: string;
  themes: ThemeTag[];
  peers: WaveSignal[];
  avgExpected: number | null;
}

function groupByTarget(signals: WaveSignal[]): TargetGroup[] {
  const map = new Map<string, TargetGroup>();
  for (const sig of signals) {
    let g = map.get(sig.target);
    if (!g) {
      g = {
        target: sig.target,
        targetName: sig.target_name,
        targetReportDate: sig.target_report_date,
        themes: [],
        peers: [],
        avgExpected: null,
      };
      map.set(sig.target, g);
    }
    g.peers.push(sig);
    for (const t of sig.shared_themes) {
      if (!g.themes.some((x) => x.key === t.key)) g.themes.push(t);
    }
  }

  const groups = [...map.values()];
  for (const g of groups) {
    g.peers.sort((a, b) => b.stats.score - a.stats.score);
    const vals = g.peers
      .map((p) => p.expected_runup_pct)
      .filter((v): v is number => v !== null);
    g.avgExpected = vals.length
      ? vals.reduce((a, b) => a + b, 0) / vals.length
      : null;
  }
  groups.sort((a, b) => {
    if (a.targetReportDate !== b.targetReportDate)
      return a.targetReportDate < b.targetReportDate ? -1 : 1;
    return (b.avgExpected ?? 0) - (a.avgExpected ?? 0);
  });
  return groups;
}

const FIRST_BATCH = 8;
const FULL_BATCH = 40;

export default function WavesPage() {
  const [recentDays, setRecentDays] = useState(14);
  const [upcomingDays, setUpcomingDays] = useState(21);
  const [data, setData] = useState<WavesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setData(null);

    api
      .waves(recentDays, upcomingDays, FIRST_BATCH)
      .then((first) => {
        if (cancelled) return;
        setData(first);
        setLoading(false);

        // Demo boards are already complete; live boards expand in the background.
        if (first.preview || !first.has_more) return;

        setLoadingMore(true);
        return api
          .waves(recentDays, upcomingDays, FULL_BATCH)
          .then((full) => {
            if (!cancelled) setData(full);
          })
          .catch(() => {
            /* keep the first batch if the expand fails */
          })
          .finally(() => {
            if (!cancelled) setLoadingMore(false);
          });
      })
      .catch((e) => {
        if (!cancelled) {
          setError(String(e));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [recentDays, upcomingDays]);

  const groups = data ? groupByTarget(data.signals) : [];
  const isPreview = Boolean(data?.preview);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Ride the wave</h1>
        <p className="text-sm text-[var(--color-muted)] mt-1 max-w-2xl">
          Grouped by the name reporting next. Each card shows the peers that already
          reported and how this stock has historically drifted into its own print after
          each one — the SNOW&nbsp;→&nbsp;ORCL setup, quantified.
        </p>
      </div>

      {isPreview ? (
        <PaywallBanner note={data?.preview_note} title="Peer waves — demo board" />
      ) : null}

      <div className="flex flex-wrap gap-4 mb-6 text-sm">
        <Slider label="Peer reported within" value={recentDays} onChange={setRecentDays} />
        <Slider label="Target reports within" value={upcomingDays} onChange={setUpcomingDays} />
      </div>

      {loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState title="Couldn't reach the API." hint="Is the backend running?" />
      ) : groups.length === 0 ? (
        <EmptyState
          title="No active wave setups in this window."
          hint="Widen the windows above, or refresh data so more peers and upcoming prints are tracked."
        />
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {groups.map((g) => (
              <TargetGroupCard key={g.target} group={g} blur={isPreview} />
            ))}
          </div>
          {loadingMore ? (
            <div className="mt-4 flex items-center justify-center gap-2 text-sm text-[var(--color-muted)]">
              <span className="h-3.5 w-3.5 rounded-full border-2 border-[var(--color-edge)] border-t-[var(--color-accent)] animate-spin" />
              Loading more setups…
            </div>
          ) : null}
          {!isPreview && data?.has_more && !loadingMore ? (
            <div className="mt-4 flex justify-center">
              <button
                type="button"
                onClick={() => {
                  const next = Math.min((data.limit ?? FIRST_BATCH) + 20, 80);
                  setLoadingMore(true);
                  api
                    .waves(recentDays, upcomingDays, next)
                    .then(setData)
                    .catch((e) => setError(String(e)))
                    .finally(() => setLoadingMore(false));
                }}
                className="px-4 py-2 rounded-lg text-sm font-medium border border-[var(--color-edge)] hover:bg-[var(--color-panel-2)]"
              >
                Load more
              </button>
            </div>
          ) : null}
          {isPreview ? (
            <PaywallFade label="Unlock the live peer-wave board with Pro" />
          ) : null}
        </>
      )}
    </div>
  );
}

function TargetGroupCard({ group, blur }: { group: TargetGroup; blur: boolean }) {
  const bullish = (group.avgExpected ?? 0) >= 0;
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <Link
            href={`/company/${group.target}`}
            className="text-xl font-bold hover:text-[var(--color-accent)]"
          >
            {group.target}
          </Link>
          {group.targetName ? (
            <span className="text-sm text-[var(--color-muted)] ml-2">
              {group.targetName}
            </span>
          ) : null}
          <div className="text-sm text-[var(--color-muted)] mt-0.5">
            reports {fmtDate(group.targetReportDate)}
          </div>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {group.themes.map((t) => (
              <ThemePill key={t.key} theme={t} />
            ))}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
            Avg expected run-up
            <InfoTip text={glossary.expected_runup} />
          </div>
          <div className={`text-2xl font-bold ${moveClass(group.avgExpected)}`}>
            <BlurValue active={blur}>{signedPct(group.avgExpected)}</BlurValue>
          </div>
          <div className="text-xs text-[var(--color-muted)]">
            across {group.peers.length} peer{group.peers.length === 1 ? "" : "s"}
            {" · "}
            <BlurValue active={blur}>
              <span style={{ color: bullish ? "#28c08a" : "#f0556d" }}>
                {bullish ? "bullish" : "bearish"}
              </span>
            </BlurValue>
          </div>
        </div>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[var(--color-muted)] text-[11px] uppercase tracking-wide">
              <th className="py-1.5 pr-3">Peer</th>
              <th className="py-1.5 pr-3">Reported</th>
              <th className="py-1.5 pr-3 cursor-help" title={glossary.move}>
                Its move
              </th>
              <th className="py-1.5 pr-3 cursor-help" title={glossary.expected_runup}>
                Exp. run-up
              </th>
              <th className="py-1.5 pr-3 cursor-help" title={glossary.win_rate}>
                Win
              </th>
              <th className="py-1.5 pr-0 cursor-help" title={glossary.sample}>
                n
              </th>
            </tr>
          </thead>
          <tbody>
            {group.peers.map((p) => (
              <tr key={p.trigger} className="border-t border-[var(--color-edge)]">
                <td className="py-2 pr-3">
                  <Link
                    href={`/company/${p.trigger}`}
                    className="font-semibold hover:text-[var(--color-accent)]"
                  >
                    {p.trigger}
                  </Link>
                </td>
                <td className="py-2 pr-3 text-[var(--color-muted)]">
                  {fmtDate(p.trigger_report_date)}
                </td>
                <td className={`py-2 pr-3 font-medium ${moveClass(p.trigger_move_pct)}`}>
                  <BlurValue active={blur}>
                    {signedPct(p.trigger_move_pct)}
                    {p.trigger_beat === true ? (
                      <span className="text-[var(--color-muted)] text-xs"> · beat</span>
                    ) : p.trigger_beat === false ? (
                      <span className="text-[var(--color-muted)] text-xs"> · miss</span>
                    ) : null}
                  </BlurValue>
                </td>
                <td className={`py-2 pr-3 font-medium ${moveClass(p.expected_runup_pct)}`}>
                  <BlurValue active={blur}>{signedPct(p.expected_runup_pct)}</BlurValue>
                </td>
                <td className="py-2 pr-3">
                  <BlurValue active={blur}>{pct(p.stats.win_rate, 0)}</BlurValue>
                </td>
                <td className="py-2 pr-0">
                  <BlurValue active={blur}>{p.stats.sample_size}</BlurValue>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Slider({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex items-center gap-2">
      <span className="text-[var(--color-muted)]">{label}</span>
      <input
        type="range"
        min={3}
        max={45}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="accent-[var(--color-accent)]"
      />
      <span className="w-12 font-medium">{value}d</span>
    </label>
  );
}
