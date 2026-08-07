"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, RankedSetup } from "@/lib/api";
import { signedPct } from "@/lib/format";
import { useAuthReady } from "@/lib/useAuthReady";

function boardsHref(focus: RankedSetup | null): string {
  if (focus?.board_href?.startsWith("/")) {
    if (focus.board_href.includes("wave")) return "/boards?tab=waves";
    if (focus.board_href.includes("drift")) return "/boards?tab=drift";
  }
  if (focus?.kind === "drift") return "/boards?tab=drift";
  return "/boards?tab=waves";
}

/** One-line Today lead on Calendar — stays out of the way of the card grid. */
export function DigestStrip() {
  const { ready, accessToken } = useAuthReady();
  const [focus, setFocus] = useState<RankedSetup | null>(null);
  const [changeLine, setChangeLine] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    Promise.all([api.rankedSetups(1, accessToken), api.digestToday(accessToken)])
      .then(([r, d]) => {
        if (cancelled) return;
        setFocus(r.focus ?? r.setups?.[0] ?? null);
        const bullet = d.bullets?.find((b) => b.kind !== "none") ?? d.bullets?.[0];
        setChangeLine(bullet?.text ?? null);
      })
      .catch(() => {
        /* calendar still works */
      });
    return () => {
      cancelled = true;
    };
  }, [ready, accessToken]);

  if (!focus && !changeLine) return null;

  const href = boardsHref(focus);
  const cta =
    focus?.kind === "wave" ? "Waves →" : focus ? "Drift →" : "Boards →";

  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <span className="shrink-0 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-accent)]">
        Today
      </span>
      {focus ? (
        <p className="min-w-0 flex-1 truncate text-[var(--color-muted)]">
          <span className="font-semibold text-white">{focus.ticker}</span>
          <span> · {focus.headline}</span>
          {focus.edge_pct != null ? (
            <span> ({signedPct(focus.edge_pct, 1)})</span>
          ) : null}
          {changeLine ? (
            <span className="hidden sm:inline"> · {changeLine}</span>
          ) : null}
        </p>
      ) : (
        <p className="min-w-0 flex-1 truncate text-[var(--color-muted)]">{changeLine}</p>
      )}
      <Link
        href={href}
        className="shrink-0 font-medium text-[var(--color-accent)] hover:underline"
      >
        {cta}
      </Link>
    </div>
  );
}
