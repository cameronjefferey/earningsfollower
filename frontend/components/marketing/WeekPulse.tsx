"use client";

import { useMemo } from "react";
import { pct } from "@/lib/format";
import { useMarketingData } from "./MarketingData";

/**
 * Live one-line proof strip for the ad landing hero: how many names report
 * this week, how many are priced for big swings, and the single biggest
 * implied move. Renders nothing until real data is in (no skeleton - the
 * hero reads fine without it).
 */
export function WeekPulse() {
  const { week } = useMarketingData();

  const stats = useMemo(() => {
    const cards = week.data ?? [];
    if (!cards.length) return null;
    const tickers = new Set(cards.map((c) => c.ticker));
    const implied = cards.filter((c) => c.implied_move_pct != null);
    if (!implied.length) return null;
    const big = new Set(
      implied
        .filter((c) => Math.abs(c.implied_move_pct!) >= 0.08)
        .map((c) => c.ticker)
    ).size;
    const top = [...implied].sort(
      (a, b) => Math.abs(b.implied_move_pct!) - Math.abs(a.implied_move_pct!)
    )[0];
    return { names: tickers.size, big, top };
  }, [week.data]);

  if (!stats) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
      <div>
        <span className="font-semibold text-white tabular">{stats.names}</span>{" "}
        <span className="text-[var(--m-muted)]">names report this week</span>
      </div>
      <div>
        <span className="font-semibold text-white tabular">{stats.big}</span>{" "}
        <span className="text-[var(--m-muted)]">priced for a ±8%+ swing</span>
      </div>
      <div>
        <span className="text-[var(--m-muted)]">biggest:</span>{" "}
        <span className="font-semibold text-white">
          {stats.top.ticker}{" "}
          <span className="tabular">±{pct(Math.abs(stats.top.implied_move_pct!), 1)}</span>
        </span>
      </div>
    </div>
  );
}
