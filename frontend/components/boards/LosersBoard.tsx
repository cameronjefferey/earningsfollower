"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ReversalWatch } from "@/lib/api";
import { Card, EmptyState, Spinner } from "@/components/ui";
import { UpdatedAt } from "@/components/UpdatedAt";
import { fmtDate } from "@/lib/format";

export function LosersBoard({ embedded = false }: { embedded?: boolean }) {
  const [data, setData] = useState<ReversalWatch | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .reversal()
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load the 5-day loser list.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!data && !error) return <Spinner />;

  const names = data?.candidates ?? [];
  const skipped = data?.skipped_earn ?? [];
  const asOf = data?.as_of ? fmtDate(data.as_of) : null;

  return (
    <div>
      {!embedded ? (
        <h1 className="text-2xl font-bold tracking-tight mb-2">5-day losers</h1>
      ) : null}
      <p className="text-sm text-[var(--color-muted)] max-w-2xl mb-4">
        The S&amp;P names the book actually ranks: worst five-session drops,
        earnings window skipped, sized 1–3% by how deep the washout is.
        {asOf ? ` Through ${asOf}.` : ""}
        {data?.holding ? " This cohort is already open." : ""}
      </p>
      <div className="mb-3">
        <UpdatedAt value={data?.updated_at ?? null} />
      </div>
      {error ? (
        <EmptyState title="List unavailable" hint={error} />
      ) : names.length ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {names.map((c) => (
            <Link key={c.ticker} href={`/company/${c.ticker}`}>
              <Card className="p-4 hover:border-[#fbbf24]/50">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-mono text-lg font-semibold">{c.ticker}</span>
                  <span className="tabular text-[#f0556d] font-semibold">
                    {(c.ret_5 * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="mt-2 text-xs text-[var(--color-muted)]">
                  {c.conviction ? `${c.conviction} conviction` : "ranked"}
                  {c.risk_frac != null
                    ? ` · ${(c.risk_frac * 100).toFixed(0)}% of the book`
                    : ""}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No names yet"
          hint="The list publishes from the paper run. Check back after the next session if this is the first day."
        />
      )}
      {skipped.length ? (
        <p className="text-xs text-[var(--color-muted)] mt-4">
          Skipped, earnings too close: {skipped.slice(0, 8).map((s) => s.ticker).join(", ")}
        </p>
      ) : null}
    </div>
  );
}
