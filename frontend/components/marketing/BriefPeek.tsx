"use client";

import Link from "next/link";
import { RankedSetup } from "@/lib/api";
import { signedPct } from "@/lib/format";
import { useMarketingData } from "./MarketingData";

function kindLabel(kind: RankedSetup["kind"]): string {
  if (kind === "wave") return "Peer wave";
  if (kind === "drift") return "Post-report drift";
  return kind;
}

/**
 * Public teaser for Pro boards. Shows the shape of a live setup (kind, ticker,
 * why) but never the full plan - that's the Pro payoff, and this runs
 * unauthenticated, so we lock those rows regardless of backend redaction.
 */
export function BriefPeek() {
  const { focus } = useMarketingData();
  const boardsHref =
    focus.data?.kind === "wave" ? "/boards?tab=waves" : "/boards?tab=drift";

  return (
    <div className="m-mid-product">
      <div className="flex items-center justify-between gap-2 mb-3">
        <span className="text-xs uppercase tracking-[0.14em] text-[var(--m-muted)]">
          Live board peek
        </span>
        <Link href={boardsHref} className="text-xs text-[var(--m-accent)] hover:underline">
          Open boards
        </Link>
      </div>

      {focus.failed ? (
        <div className="py-6 text-sm text-[var(--m-muted)]">
          <p>Boards are refreshing.</p>
          <Link
            href="/boards"
            className="mt-2 inline-block text-[var(--m-accent)] hover:underline"
          >
            Open boards →
          </Link>
        </div>
      ) : focus.data ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-wider text-[var(--m-muted)]">
            <span className="text-[var(--m-accent)]">{kindLabel(focus.data.kind)}</span>
            {focus.data.sample_size != null ? (
              <span className="tabular">n={focus.data.sample_size}</span>
            ) : null}
            {focus.data.sample_tier ? <span>· {focus.data.sample_tier}</span> : null}
          </div>
          <div className="mt-2 flex items-baseline justify-between gap-3">
            <span className="text-2xl font-semibold text-white tracking-tight">
              {focus.data.ticker}
            </span>
            {focus.data.edge_pct != null ? (
              <span className="tabular text-[var(--m-accent)] text-sm">
                {signedPct(focus.data.edge_pct, 1)}
              </span>
            ) : null}
          </div>
          <p className="mt-2 text-sm text-white/75 leading-snug">
            {focus.data.headline}
          </p>

          <div className="mt-4 border-t border-[var(--m-line)] pt-3 space-y-1.5">
            {(["Action", "Watch", "Drop-if"] as const).map((row) => (
              <div
                key={row}
                className="flex items-center justify-between gap-3 text-sm"
              >
                <span className="text-[var(--m-muted)]">{row}</span>
                <span className="text-[10px] uppercase tracking-wider rounded px-1.5 py-0.5 border border-[var(--m-line)] text-[var(--m-muted)]">
                  Pro
                </span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="space-y-3 py-2">
          <div className="h-3 w-28 rounded skeleton" />
          <div className="h-7 w-20 rounded skeleton" />
          <div className="h-4 w-full rounded skeleton" />
          <div className="h-4 w-[80%] rounded skeleton" />
        </div>
      )}
    </div>
  );
}
