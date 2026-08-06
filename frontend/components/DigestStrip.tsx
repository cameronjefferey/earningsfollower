"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, RankedSetup } from "@/lib/api";
import { Card } from "@/components/ui";
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

/** Compact Today lead on Calendar — points into Boards, not a Brief page. */
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
    focus?.kind === "wave" ? "Open Waves →" : focus ? "Open Drift →" : "Open Boards →";

  return (
    <Card className="p-4 mb-6 border-[var(--color-accent)]/25">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-accent)] mb-1">
            Today
          </div>
          {focus ? (
            <>
              <p className="text-base">
                <span className="font-semibold text-white">{focus.ticker}</span>
                <span className="text-[var(--color-muted)]"> · </span>
                <span>{focus.headline}</span>
                {focus.edge_pct != null ? (
                  <span className="text-[var(--color-muted)]">
                    {" "}
                    ({signedPct(focus.edge_pct, 1)})
                  </span>
                ) : null}
              </p>
              {changeLine ? (
                <p className="text-sm text-[var(--color-muted)] mt-1">{changeLine}</p>
              ) : null}
            </>
          ) : (
            <p className="text-sm text-[var(--color-muted)]">{changeLine}</p>
          )}
        </div>
        <Link
          href={href}
          className="shrink-0 px-3 py-1.5 rounded-lg text-sm font-medium bg-[var(--color-accent)]/15 text-[var(--color-accent)] hover:bg-[var(--color-accent)]/25"
        >
          {cta}
        </Link>
      </div>
    </Card>
  );
}
