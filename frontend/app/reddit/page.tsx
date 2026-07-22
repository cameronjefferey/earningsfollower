"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, RedditResponse, RedditSignal } from "@/lib/api";
import { PaywallBanner, PaywallFade } from "@/components/PaywallBanner";
import { Card, EmptyState, Spinner } from "@/components/ui";

const DIR_COLOR: Record<string, string> = {
  bullish: "#28c08a",
  bearish: "#f0556d",
  neutral: "#8a97b1",
};

const CONVICTION_COLOR: Record<string, string> = {
  high: "#28c08a",
  medium: "#f0a85b",
  low: "#8a97b1",
};

const PUMP_COLOR: Record<string, string> = {
  low: "#28c08a",
  medium: "#f0a85b",
  high: "#f0556d",
};

const ACCENT = "#ff6a3d";

function Pill({ text, color }: { text: string; color: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold border whitespace-nowrap"
      style={{ color, borderColor: `${color}55`, backgroundColor: `${color}1a` }}
    >
      {text}
    </span>
  );
}

export default function RedditPage() {
  const [data, setData] = useState<RedditResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load(refresh = false) {
    if (refresh) setScanning(true);
    else setLoading(true);
    setError(null);
    api
      .reddit(refresh)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => {
        setLoading(false);
        setScanning(false);
      });
  }

  useEffect(() => {
    load(false);
  }, []);

  const signals = data?.signals ?? [];
  const isPreview = Boolean(data?.preview);

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Reddit <span style={{ color: ACCENT }}>sentiment</span>
          </h1>
          <p className="text-sm text-[var(--color-muted)] mt-1 max-w-2xl">
            Monitors retail subreddits for chatter on names we track. A ticker only
            surfaces once mentions clear a floor <em>and</em> accelerate past their own
            baseline (the velocity / anti-pump guard). Each signal is scored into a
            directional lean and a pump-risk read — by an LLM when configured, else a
            transparent keyword heuristic. The paper trader turns qualifying signals into
            small, defined-risk debit spreads tagged <span style={{ color: ACCENT }}>reddit</span>.
          </p>
        </div>
        {!isPreview ? (
          <button
            onClick={() => load(true)}
            disabled={scanning}
            className="shrink-0 px-3 py-1.5 rounded-lg text-sm font-medium border border-[var(--color-edge)] hover:bg-[var(--color-panel-2)] disabled:opacity-50"
          >
            {scanning ? "Scanning…" : "Scan now"}
          </button>
        ) : null}
      </div>

      {isPreview ? (
        <PaywallBanner note={data?.preview_note} title="Preview: Reddit signals" />
      ) : null}

      {loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState title="Couldn't reach the API." hint="Is the backend running?" />
      ) : signals.length === 0 ? (
        <EmptyState
          title="No Reddit signals yet."
          hint='Hit "Scan now" to poll Reddit, or enable the strategy (PAPER_REDDIT_ENABLED=true) so the paper worker scans on each run. Signals need enough mentions and acceleration before they show up.'
        />
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {signals.map((s) => (
              <SignalCard key={`${s.ticker}-${s.scan_date}`} signal={s} />
            ))}
          </div>
          {isPreview ? (
            <PaywallFade label="Unlock the full Reddit feed and live scans with Pro" />
          ) : null}
        </>
      )}
    </div>
  );
}

function SignalCard({ signal: s }: { signal: RedditSignal }) {
  const dir = DIR_COLOR[s.direction] ?? "#8a97b1";
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <Link
              href={`/company/${s.ticker}`}
              className="text-xl font-bold hover:text-[var(--color-accent)]"
            >
              {s.ticker}
            </Link>
            <Pill text={s.direction} color={dir} />
            <Pill text={`${s.conviction} conviction`} color={CONVICTION_COLOR[s.conviction] ?? "#8a97b1"} />
            <Pill text={`pump ${s.pump_risk}`} color={PUMP_COLOR[s.pump_risk] ?? "#8a97b1"} />
            {s.is_noise ? <Pill text="noise" color="#5a6680" /> : null}
            <Pill text={s.scored_by} color="#5b8cff" />
          </div>
          <div className="flex flex-wrap gap-1.5 mt-2 text-[11px] text-[var(--color-muted)]">
            {s.subreddits.map((sub) => (
              <span
                key={sub}
                className="rounded border border-[var(--color-edge)] px-1.5 py-0.5 font-mono"
              >
                r/{sub}
              </span>
            ))}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
            Mention velocity
          </div>
          <div className="text-2xl font-bold" style={{ color: ACCENT }}>
            {s.mention_velocity != null ? `${s.mention_velocity.toFixed(1)}x` : "—"}
          </div>
          <div className="text-xs text-[var(--color-muted)]">
            {s.mention_count} mentions
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mt-4 text-center">
        <div className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-2 py-2">
          <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
            Sentiment
          </div>
          <div className="text-sm font-semibold" style={{ color: dir }}>
            {s.sentiment != null ? s.sentiment.toFixed(2) : "—"}
          </div>
        </div>
        <div className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-2 py-2">
          <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
            Score
          </div>
          <div className="text-sm font-semibold">
            {s.score != null ? s.score.toFixed(2) : "—"}
          </div>
        </div>
      </div>

      {s.rationale ? (
        <p className="mt-3 text-xs leading-relaxed text-[var(--color-muted)]">
          {s.rationale}
        </p>
      ) : null}

      {s.samples.length ? (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-[var(--color-muted)] hover:text-white select-none">
            Source threads
          </summary>
          <ul className="mt-2 space-y-1.5 list-disc pl-5 text-[var(--color-muted)]">
            {s.samples.map((url, i) => (
              <li key={i}>
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-[var(--color-accent)] break-all"
                >
                  {url.replace("https://www.reddit.com", "")}
                </a>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </Card>
  );
}
