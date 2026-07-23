"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, DigestResponse, TrackRecordResponse } from "@/lib/api";
import { Card } from "@/components/ui";
import { pct } from "@/lib/format";
import { useAuthReady } from "@/lib/useAuthReady";

export function DigestStrip() {
  const { ready, accessToken } = useAuthReady();
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [track, setTrack] = useState<TrackRecordResponse | null>(null);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    Promise.all([api.digestToday(accessToken), api.trackRecord(accessToken)])
      .then(([d, t]) => {
        if (cancelled) return;
        setDigest(d);
        setTrack(t);
      })
      .catch(() => {
        /* homepage still works without the strip */
      });
    return () => {
      cancelled = true;
    };
  }, [ready, accessToken]);

  if (!digest && !track) return null;

  const bullets = (digest?.bullets ?? []).slice(0, 4);
  const overall = track?.overall;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-6">
      <Card className="p-4 lg:col-span-2">
        <div className="flex items-baseline justify-between gap-3 mb-2">
          <h2 className="font-semibold text-sm">Today&apos;s changes</h2>
          <Link
            href="/digest"
            className="text-xs text-[var(--color-accent)] hover:underline shrink-0"
          >
            Full digest →
          </Link>
        </div>
        {bullets.length ? (
          <ul className="space-y-1.5">
            {bullets.map((b, i) => (
              <li key={i} className="text-sm text-[var(--color-muted)] flex gap-2">
                <span className="text-[var(--color-accent)]">•</span>
                <span>{b.text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-[var(--color-muted)]">
            Digest builds after the next data refresh.
          </p>
        )}
      </Card>
      <Card className="p-4">
        <div className="flex items-baseline justify-between gap-3 mb-2">
          <h2 className="font-semibold text-sm">Track record</h2>
          <Link
            href="/track-record"
            className="text-xs text-[var(--color-accent)] hover:underline shrink-0"
          >
            Details →
          </Link>
        </div>
        {overall && overall.closed_count > 0 ? (
          <div className="text-sm text-[var(--color-muted)] space-y-1">
            <div>
              <span className="text-white font-semibold">
                {pct(overall.win_rate, 0)}
              </span>{" "}
              win rate
            </div>
            <div>n={overall.closed_count} closed paper trades</div>
            {overall.win_rate_ci_low != null ? (
              <div className="text-xs">Wilson low {pct(overall.win_rate_ci_low, 0)}</div>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-[var(--color-muted)]">
            Paper scorecard fills as trades close.
          </p>
        )}
      </Card>
    </div>
  );
}
