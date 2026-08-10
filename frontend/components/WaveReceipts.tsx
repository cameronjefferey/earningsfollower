"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, WaveReceipt, WaveReceiptsResponse } from "@/lib/api";
import { fmtDate, signedPct } from "@/lib/format";

/** Proof, not promises: how the waves that already resolved actually played out.
 *
 * Every qualifying wave in the window is scored - winners and losers - so this
 * reads as a track record rather than a highlight reel. Public data on purpose:
 * receipts are what convince a free user the Pro board is worth paying for.
 */
export function WaveReceipts({
  variant = "board",
  limit = 8,
}: {
  variant?: "board" | "marketing";
  limit?: number;
}) {
  const [data, setData] = useState<WaveReceiptsResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .waveReceipts()
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        /* proof section only - the page works without it */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const summary = data?.summary;
  // A tiny sample reads as cherry-picking; wait until there's a real record.
  const minCount = variant === "marketing" ? 5 : 3;
  if (!data || !summary || summary.count < minCount) return null;

  const receipts = data.receipts.slice(0, variant === "marketing" ? 3 : limit);
  const followPct =
    summary.follow_rate != null ? Math.round(summary.follow_rate * 100) : null;

  if (variant === "marketing") {
    return (
      <div className="rounded-xl border border-[var(--m-line)] bg-white/[0.02] p-4 sm:p-5">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--m-accent)]">
          Receipts, last {data.days_back} days
        </div>
        <p className="mt-2 text-sm text-[var(--m-muted)] leading-relaxed">
          <span className="font-semibold text-white tabular">{summary.count}</span>{" "}
          waves resolved. Riding the wave direction was right{" "}
          <span className="font-semibold text-white tabular">
            {summary.followed} of {summary.count}
          </span>
          {summary.avg_edge_pct != null ? (
            <>
              , avg{" "}
              <span className="font-semibold text-white tabular">
                {signedPct(summary.avg_edge_pct)}
              </span>{" "}
              into the print
            </>
          ) : null}
          . Winners and losers both counted.
        </p>
        <div className="mt-3 space-y-1.5">
          {receipts.map((r) => (
            <div key={`${r.target}-${r.target_report_date}`} className="text-sm">
              <span className="font-semibold text-white">{r.target}</span>{" "}
              <span className="text-[var(--m-muted)]">{receiptLine(r)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="mt-8">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold tracking-tight">
          Receipts: waves that already resolved
        </h2>
        <span className="text-xs text-[var(--color-muted)]">
          last {data.days_back} days · winners and losers both counted
        </span>
      </div>
      <p className="mt-1 text-sm text-[var(--color-muted)]">
        {summary.count} waves resolved. Riding the wave direction was right{" "}
        <span className="font-medium text-white tabular">
          {summary.followed} of {summary.count}
          {followPct != null ? ` (${followPct}%)` : ""}
        </span>
        {summary.avg_edge_pct != null ? (
          <>
            , average{" "}
            <span className="font-medium text-white tabular">
              {signedPct(summary.avg_edge_pct)}
            </span>{" "}
            into the print
          </>
        ) : null}
        .
      </p>
      <div className="mt-3 divide-y divide-[var(--color-edge)] rounded-xl border border-[var(--color-edge)] bg-[var(--color-panel)]/50">
        {receipts.map((r) => (
          <div
            key={`${r.target}-${r.target_report_date}`}
            className="flex flex-wrap items-center gap-x-2 gap-y-0.5 px-4 py-2.5 text-sm"
          >
            <Link
              href={`/company/${r.target}`}
              className="font-semibold text-white hover:text-[var(--color-accent)]"
            >
              {r.target}
            </Link>
            <span className="text-[var(--color-muted)]">{peersLine(r)}</span>
            <span className="ml-auto flex items-center gap-1.5">
              <span
                className={`font-semibold tabular ${
                  r.followed ? "text-[var(--color-up)]" : "text-[var(--color-down)]"
                }`}
              >
                {signedPct(r.actual_runup_pct)}
              </span>
              <span className="text-xs text-[var(--color-muted)]">
                into {fmtDate(r.target_report_date)} {r.followed ? "✓" : "✗"}
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function peersLine(r: WaveReceipt): string {
  const parts = r.peers
    .slice(0, 3)
    .map((p) =>
      p.move_pct != null ? `${p.ticker} ${signedPct(p.move_pct)}` : p.ticker
    );
  const extra = r.peer_count > 3 ? ` +${r.peer_count - 3}` : "";
  return `${r.direction} wave · ${parts.join(", ")}${extra} →`;
}

function receiptLine(r: WaveReceipt): string {
  const run = signedPct(r.actual_runup_pct);
  return `${r.peer_count} peers printed, ran ${run} into its report ${
    r.followed ? "✓" : "✗"
  }`;
}
