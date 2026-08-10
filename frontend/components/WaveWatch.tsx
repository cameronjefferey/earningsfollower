"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, WaveWatchItem } from "@/lib/api";
import { fmtDate, signedPct } from "@/lib/format";

/** Real waves forming right now, shown free: the teaser for the Pro board.
 *
 * Targets, report dates, and which peers already ripped are visible; the
 * expected run-up / win rate / history stay behind Pro. `variant` switches
 * between app chrome (calendar) and marketing chrome (/start).
 */
export function WaveWatch({
  variant = "app",
  limit = 3,
}: {
  variant?: "app" | "marketing";
  limit?: number;
}) {
  const [waves, setWaves] = useState<WaveWatchItem[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .waveWatch()
      .then((res) => {
        if (!cancelled) setWaves(res.waves ?? []);
      })
      .catch(() => {
        /* teaser only - the page works without it */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!waves || waves.length === 0) return null;
  const items = waves.slice(0, limit);

  if (variant === "marketing") {
    return (
      <div className="rounded-xl border border-[var(--m-line)] bg-white/[0.02] p-4 sm:p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--m-accent)]">
            Live right now
          </div>
          <Link
            href="/boards?tab=waves"
            className="text-sm font-medium text-[var(--m-accent)] hover:underline"
          >
            See the waves →
          </Link>
        </div>
        <div className="mt-3 space-y-2">
          {items.map((w) => (
            <div
              key={w.target}
              className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm"
            >
              <span className="font-semibold text-white">{w.target}</span>
              <span className="text-[var(--m-muted)]">
                {waveLine(w)}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <span className="shrink-0 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-accent)]">
        Waves forming
      </span>
      <p className="min-w-0 flex-1 truncate text-[var(--color-muted)]">
        {items.map((w, i) => (
          <span key={w.target}>
            {i > 0 ? " · " : ""}
            <Link
              href={`/company/${w.target}`}
              className="font-semibold text-white hover:text-[var(--color-accent)]"
            >
              {w.target}
            </Link>
            <span> {waveLine(w)}</span>
          </span>
        ))}
      </p>
      <Link
        href="/boards?tab=waves"
        className="shrink-0 font-medium text-[var(--color-accent)] hover:underline"
      >
        Waves →
      </Link>
    </div>
  );
}

function waveLine(w: WaveWatchItem): string {
  const when = w.target_report_date ? `reports ${fmtDate(w.target_report_date)}` : "reports soon";
  if (w.ripped_count > 0) {
    const best = [...w.peers]
      .filter((p) => p.move_pct != null)
      .sort((a, b) => (b.move_pct ?? 0) - (a.move_pct ?? 0))[0];
    const rip = best
      ? `${w.ripped_count} peer${w.ripped_count === 1 ? "" : "s"} ripped (${best.ticker} ${signedPct(best.move_pct)})`
      : `${w.ripped_count} peer${w.ripped_count === 1 ? "" : "s"} ripped`;
    return `${rip}, ${when}`;
  }
  return `${w.peer_count} peers reported, ${when}`;
}
