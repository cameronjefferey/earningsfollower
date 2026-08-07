"use client";

import Link from "next/link";
import { useMemo } from "react";
import { EarningsCard } from "@/lib/api";
import { fmtDate, marketCap, pct, timingLabel } from "@/lib/format";
import { useMarketingData } from "./MarketingData";

/** Absolute move in percentage points (API stores fractions). */
function moveScore(c: EarningsCard): number {
  const frac = c.implied_move_pct ?? c.avg_abs_move_pct;
  if (frac == null || Number.isNaN(frac)) return 3;
  return Math.abs(frac) * 100;
}

function cellTone(m: number): string {
  if (m >= 12) return "m-heat-hot";
  if (m >= 8) return "m-heat-warm";
  if (m >= 5) return "m-heat-mid";
  return "m-heat-cool";
}

function dedupeByTicker(cards: EarningsCard[]): EarningsCard[] {
  const best = new Map<string, EarningsCard>();
  for (const c of cards) {
    const prev = best.get(c.ticker);
    if (!prev || moveScore(c) > moveScore(prev)) best.set(c.ticker, c);
  }
  return [...best.values()];
}

/** Ambient mini tiles for hero / CTA backdrop only. Never shows text states. */
function AmbientHeat({ cards }: { cards: EarningsCard[] }) {
  return (
    <div className="m-heat m-heat-dense">
      {cards.map((c) => {
        const m = moveScore(c);
        const scale = Math.min(1.35, 0.72 + m / 22);
        const frac = c.implied_move_pct ?? c.avg_abs_move_pct;
        return (
          <div
            key={`${c.ticker}-${c.date}`}
            className={`m-heat-cell ${cellTone(m)}`}
            style={{ ["--heat-scale" as string]: String(scale) }}
            aria-hidden="true"
          >
            <span className="m-heat-ticker">{c.ticker}</span>
            <span className="m-heat-meta tabular">{pct(frac, 0)}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Live week board — fewer names, more signal per card. Shares one fetch. */
export function WeekHeat({
  dense = false,
  limit,
}: {
  dense?: boolean;
  /** Cap on non-dense cards (default 6). */
  limit?: number;
}) {
  const { week } = useMarketingData();
  const max = dense ? 28 : (limit ?? 6);

  const cells = useMemo(() => {
    if (!week.data) return [];
    return dedupeByTicker(week.data)
      .sort((a, b) => moveScore(b) - moveScore(a))
      .slice(0, max);
  }, [week.data, max]);

  // Decorative backdrop: only ever render tiles (skeleton while loading,
  // nothing on empty/error) — never leak a text/error box behind the hero.
  if (dense) {
    if (week.data === null) {
      if (week.failed) return null;
      return (
        <div className="m-heat m-heat-dense" aria-hidden="true">
          {Array.from({ length: 24 }).map((_, i) => (
            <div key={i} className="m-heat-cell m-heat-skel" />
          ))}
        </div>
      );
    }
    if (!cells.length) return null;
    return <AmbientHeat cards={cells} />;
  }

  if (week.data === null && !week.failed) {
    return (
      <div className="m-priced-grid">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="m-priced-card m-priced-skel" />
        ))}
      </div>
    );
  }

  if (!cells.length) {
    return (
      <div className="m-heat-empty">
        <p>
          No live week data right now.{" "}
          <Link href="/calendar" className="text-[var(--m-accent)] underline">
            Open the calendar
          </Link>
        </p>
      </div>
    );
  }

  return (
    <div className="m-priced-grid">
      {cells.map((c) => {
        const m = moveScore(c);
        const implied = c.implied_move_pct;
        const avg = c.avg_abs_move_pct;
        const theme = c.themes[0];
        const when = timingLabel(c.timing);
        return (
          <Link
            key={`${c.ticker}-${c.date}`}
            href={`/company/${c.ticker}`}
            className={`m-priced-card ${cellTone(m)}`}
          >
            <div className="m-priced-top">
              <div className="min-w-0">
                <div className="m-priced-ticker">{c.ticker}</div>
                <div className="m-priced-name truncate">
                  {c.name ?? c.sector ?? "—"}
                </div>
              </div>
              <div className="m-priced-when shrink-0 text-right">
                <div className="tabular">{fmtDate(c.date)}</div>
                {when ? <div className="m-priced-timing">{when}</div> : null}
              </div>
            </div>

            <div className="m-priced-metrics">
              <div>
                <div className="m-priced-label">
                  {implied != null ? "Implied" : "Avg move"}
                </div>
                <div className="m-priced-move tabular">{pct(implied ?? avg)}</div>
              </div>
              <div className="text-right">
                <div className="m-priced-label">Hist. avg</div>
                <div className="m-priced-side tabular">{pct(avg)}</div>
                <div className="m-priced-label mt-2">Up rate</div>
                <div className="m-priced-side tabular">{pct(c.up_rate, 0)}</div>
              </div>
            </div>

            <div className="m-priced-foot">
              <span className="tabular">{marketCap(c.market_cap)}</span>
              {theme ? <span className="m-priced-theme">{theme.label}</span> : null}
            </div>
          </Link>
        );
      })}
    </div>
  );
}
