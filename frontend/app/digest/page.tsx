"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, DigestResponse } from "@/lib/api";
import { PaywallBanner, PaywallFade } from "@/components/PaywallBanner";
import { UpdatedAt } from "@/components/UpdatedAt";
import { Card, EmptyState, Spinner } from "@/components/ui";
import { useAuthReady } from "@/lib/useAuthReady";

export default function DigestPage() {
  const { ready, accessToken } = useAuthReady();
  const [data, setData] = useState<DigestResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    setLoading(true);
    api
      .digestToday(accessToken)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ready, accessToken]);

  const isPreview = Boolean(data?.preview);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Today&apos;s digest</h1>
        <p className="text-sm text-[var(--color-muted)] mt-1 max-w-2xl">
          What changed on the calendar and research boards since the last refresh.
        </p>
        <UpdatedAt value={data?.updated_at || data?.generated_at} />
      </div>

      {isPreview ? (
        <PaywallBanner title="Digest — preview" note={data?.preview_note} />
      ) : null}

      {!ready || loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState title="Couldn't load digest." hint="Is the backend running?" />
      ) : (
        <>
          <Card className="p-4">
            <div className="text-xs text-[var(--color-muted)] mb-3">
              {data?.date ? `As of ${data.date}` : "Latest digest"}
            </div>
            <ul className="space-y-2.5">
              {(data?.bullets ?? []).map((b, i) => (
                <li key={i} className="text-sm flex gap-2">
                  <span className="text-[var(--color-accent)] shrink-0">•</span>
                  <span>{b.text}</span>
                </li>
              ))}
            </ul>
          </Card>
          <div className="mt-4 flex flex-wrap gap-3 text-sm">
            <Link href="/waves" className="text-[var(--color-accent)] hover:underline">
              Open Waves →
            </Link>
            <Link href="/drift" className="text-[var(--color-accent)] hover:underline">
              Open Drift →
            </Link>
            <Link
              href="/track-record"
              className="text-[var(--color-accent)] hover:underline"
            >
              Track record →
            </Link>
          </div>
          {isPreview ? (
            <PaywallFade label="Unlock the full daily digest with Pro" />
          ) : null}
        </>
      )}
    </div>
  );
}
