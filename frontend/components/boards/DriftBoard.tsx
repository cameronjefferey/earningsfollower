"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, DriftResponse, DriftSetup } from "@/lib/api";
import { BlurValue } from "@/components/BlurValue";
import { PaywallBanner, PaywallFade } from "@/components/PaywallBanner";
import { Card, EmptyState, Spinner, ThemePill } from "@/components/ui";
import { InfoTip } from "@/components/InfoTip";
import { glossary } from "@/lib/glossary";
import { fmtDate, moveClass, pct, signedPct } from "@/lib/format";
import { SampleTierBadge } from "@/components/SampleTierBadge";
import { UpdatedAt } from "@/components/UpdatedAt";
import { useAuthReady } from "@/lib/useAuthReady";

const FIRST_BATCH = 6;
const FULL_BATCH = 30;

export function DriftBoard({ embedded = false }: { embedded?: boolean }) {
  const { ready, accessToken, session } = useAuthReady();
  const isAdmin = Boolean(session?.isAdmin);
  const [lookbackDays, setLookbackDays] = useState(12);
  const [directionFilter, setDirectionFilter] = useState<"all" | "long" | "short">("all");
  const [data, setData] = useState<DriftResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [moreError, setMoreError] = useState<string | null>(null);
  const [solidOnly, setSolidOnly] = useState(false);
  const fetchGen = useRef(0);

  useEffect(() => {
    if (!ready) return;
    const gen = ++fetchGen.current;
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setMoreError(null);
    setData(null);

    api
      .drift(lookbackDays, FIRST_BATCH, accessToken)
      .then(async (first) => {
        if (gen !== fetchGen.current) return;
        setData(first);
        setLoading(false);

        if (first.preview || !first.has_more) return;

        setLoadingMore(true);
        try {
          const full = await api.drift(lookbackDays, FULL_BATCH, accessToken);
          if (gen !== fetchGen.current) return;
          setData(full);
        } catch {
          /* keep the first batch if the expand fails */
        } finally {
          if (gen === fetchGen.current) setLoadingMore(false);
        }
      })
      .catch((e) => {
        if (gen !== fetchGen.current) return;
        setError(String(e));
        setLoading(false);
      });

    return () => {
      fetchGen.current += 1;
    };
  }, [ready, accessToken, lookbackDays]);

  const allSetups = data?.setups ?? [];
  const setups = allSetups.filter((s) => {
    if (directionFilter !== "all" && s.direction !== directionFilter) return false;
    if (!solidOnly) return true;
    const tier =
      s.sample_tier ?? (s.history.sample_size >= 9 ? "solid" : "ok");
    return tier === "solid";
  });
  const isPreview = Boolean(data?.preview);
  const filterEmpty = allSetups.length > 0 && setups.length === 0;

  return (
    <div>
      {embedded ? (
        <div className="mb-4">
          <p className="text-sm text-[var(--color-muted)] max-w-2xl">
            Strong prints that historically keep drifting the same way for ~5 trading
            days.
          </p>
          <UpdatedAt value={data?.updated_at} />
        </div>
      ) : (
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight">Post-earnings drift</h1>
          <p className="text-sm text-[var(--color-muted)] mt-1 max-w-2xl">
            Stocks that just delivered a strong print (beat + up move, or miss + down
            move) tend to keep moving the same direction for ~5 trading days. These are
            the live setups where this stock&apos;s own history says the drift pays.
          </p>
          <UpdatedAt value={data?.updated_at} />
        </div>
      )}

      {isPreview ? (
        <PaywallBanner
          note={data?.preview_note}
          title="Post-earnings drift — sample board"
          badge="Sample"
        />
      ) : null}

      {isAdmin && !isPreview ? <Playbook /> : null}

      <div className="flex flex-wrap items-center gap-4 mb-6 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-[var(--color-muted)]">Reported within</span>
          <input
            type="range"
            min={3}
            max={21}
            value={lookbackDays}
            onChange={(e) => setLookbackDays(Number(e.target.value))}
            className="accent-[var(--color-accent)]"
          />
          <span className="w-10 font-medium">{lookbackDays}d</span>
        </label>
        <div className="flex items-center gap-1">
          {(["all", "long", "short"] as const).map((d) => (
            <button
              key={d}
              onClick={() => setDirectionFilter(d)}
              className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${
                directionFilter === d
                  ? "bg-[var(--color-accent)]/15 text-[var(--color-accent)]"
                  : "text-[var(--color-muted)] hover:text-white hover:bg-[var(--color-panel-2)]"
              }`}
            >
              {d === "all" ? "All" : d === "long" ? "Longs" : "Shorts"}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-[var(--color-muted)] cursor-pointer">
          <input
            type="checkbox"
            checked={solidOnly}
            onChange={(e) => setSolidOnly(e.target.checked)}
            className="accent-[var(--color-accent)]"
          />
          Solid samples only
        </label>
      </div>

      {!ready || loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState title="Couldn't reach the API." hint="Is the backend running?" />
      ) : setups.length === 0 ? (
        <EmptyState
          title={
            filterEmpty
              ? `No ${directionFilter} setups in this window.`
              : "No live drift setups right now."
          }
          hint={
            filterEmpty
              ? "Try All, or widen the lookback."
              : "Setups appear after strong prints (beat + up move or miss + down move) on stocks whose history shows the drift continues. Widen the lookback, or check back after the next batch of reports."
          }
        />
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {setups.map((s) => (
              <SetupCard
                key={`${s.ticker}-${s.report_date}`}
                setup={s}
                showPlan={isAdmin && !isPreview}
                blur={isPreview}
              />
            ))}
          </div>
          {loadingMore ? (
            <div className="mt-4 flex items-center justify-center gap-2 text-sm text-[var(--color-muted)]">
              <span className="h-3.5 w-3.5 rounded-full border-2 border-[var(--color-edge)] border-t-[var(--color-accent)] animate-spin" />
              Loading more setups…
            </div>
          ) : null}
          {moreError ? (
            <p className="mt-3 text-center text-sm text-[var(--color-muted)]">{moreError}</p>
          ) : null}
          {!isPreview && data?.has_more && !loadingMore ? (
            <div className="mt-4 flex justify-center">
              <button
                type="button"
                onClick={() => {
                  const next = Math.min((data.limit ?? FIRST_BATCH) + 15, 60);
                  const gen = ++fetchGen.current;
                  setLoadingMore(true);
                  setMoreError(null);
                  api
                    .drift(lookbackDays, next, accessToken)
                    .then((full) => {
                      if (gen !== fetchGen.current) return;
                      setData(full);
                    })
                    .catch(() => {
                      if (gen !== fetchGen.current) return;
                      setMoreError("Couldn't load more — try again.");
                    })
                    .finally(() => {
                      if (gen === fetchGen.current) setLoadingMore(false);
                    });
                }}
                className="px-4 py-2 rounded-lg text-sm font-medium border border-[var(--color-edge)] hover:bg-[var(--color-panel-2)]"
              >
                Load more
              </button>
            </div>
          ) : null}
          {isPreview ? (
            <PaywallFade label="Unlock the live PEAD board with Pro" />
          ) : null}
        </>
      )}
    </div>
  );
}

function Playbook() {
  return (
    <Card className="p-4 mb-6">
      <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-2">
        The playbook
        <InfoTip text={glossary.drift_playbook} />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
        <div>
          <div className="font-semibold mb-0.5">1 · Enter early</div>
          <p className="text-[var(--color-muted)]">
            The edge is measured from the first post-earnings close. Day 0–1 is the
            best entry; after that, only buy pullbacks toward the earnings-day close.
          </p>
        </div>
        <div>
          <div className="font-semibold mb-0.5">2 · Hold ~5 trading days</div>
          <p className="text-[var(--color-muted)]">
            Exit after 5 trading days — that&apos;s the horizon the historical edge is
            measured over. Some names keep paying to 10 days; the card will say so.
          </p>
        </div>
        <div>
          <div className="font-semibold mb-0.5">3 · Respect the stop</div>
          <p className="text-[var(--color-muted)]">
            A close back through the earnings-day pivot kills the thesis. Setups that
            already broke their pivot are removed from this list automatically.
          </p>
        </div>
      </div>
    </Card>
  );
}

function DirectionBadge({ direction }: { direction: "long" | "short" }) {
  const long = direction === "long";
  const color = long ? "#28c08a" : "#f0556d";
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold border uppercase tracking-wide"
      style={{ color, borderColor: `${color}55`, backgroundColor: `${color}1a` }}
    >
      {long ? "Long" : "Short"}
    </span>
  );
}

function QualityBadge({ quality }: { quality: "fresh" | "ok" | "late" }) {
  const map = {
    fresh: { label: "Fresh entry", color: "#28c08a" },
    ok: { label: "Still tradeable", color: "#f0a85b" },
    late: { label: "Late", color: "#8a97b1" },
  } as const;
  const v = map[quality];
  return (
    <span
      title={glossary.drift_entry_quality}
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium border cursor-help"
      style={{ color: v.color, borderColor: `${v.color}55`, backgroundColor: `${v.color}1a` }}
    >
      {v.label}
    </span>
  );
}

function SetupCard({
  setup: s,
  showPlan,
  blur,
}: {
  setup: DriftSetup;
  showPlan: boolean;
  blur: boolean;
}) {
  const plan = showPlan ? s.plan : null;
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
            <DirectionBadge direction={s.direction} />
            <SampleTierBadge tier={s.sample_tier} />
            {plan ? <QualityBadge quality={plan.entry_quality} /> : null}
          </div>
          {s.name ? (
            <div className="text-sm text-[var(--color-muted)] mt-0.5">{s.name}</div>
          ) : null}
          <div className="text-sm text-[var(--color-muted)] mt-0.5">
            reported {fmtDate(s.report_date)} ·{" "}
            <BlurValue active={blur}>
              <span className={moveClass(s.move_pct)}>{signedPct(s.move_pct)}</span> on the
              print{s.beat ? " · beat" : " · miss"}
            </BlurValue>
          </div>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {s.themes.map((t) => (
              <ThemePill key={t.key} theme={t} />
            ))}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
            Hist. 5-day drift
            <InfoTip text={glossary.drift_hist_edge} />
          </div>
          <div className={`text-2xl font-bold ${moveClass(s.history.avg_drift_5d_pct)}`}>
            <BlurValue active={blur}>{signedPct(s.history.avg_drift_5d_pct)}</BlurValue>
          </div>
          <div className="text-xs text-[var(--color-muted)]">
            <BlurValue active={blur}>
              {pct(s.history.win_rate_5d, 0)} win
              {s.win_rate_ci_low != null ? ` (≥${pct(s.win_rate_ci_low, 0)})` : ""}
              {" · "}n={s.history.sample_size}
            </BlurValue>
          </div>
        </div>
      </div>

      <div
        className={`grid gap-2 mt-4 text-center ${
          plan ? "grid-cols-3" : "grid-cols-2"
        }`}
      >
        <MiniStat
          label="Drift so far"
          value={signedPct(s.live.drift_so_far_pct)}
          valueClass={moveClass(s.live.drift_so_far_pct)}
          blur={blur}
        />
        <MiniStat
          label="Days in / left"
          value={`${s.live.trading_days_in} / ${s.live.trading_days_left}`}
          blur={blur}
        />
        {plan ? (
          <MiniStat
            label="Stop level"
            value={s.live.stop_level !== null ? `$${s.live.stop_level}` : "—"}
            blur={blur}
          />
        ) : null}
      </div>

      {plan ? (
        <div className="mt-4 rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] p-3 text-sm space-y-2">
          <PlanRow label="Entry" text={plan.entry} />
          <PlanRow label="Exit" text={plan.exit} />
          <PlanRow label="Stop" text={plan.stop} />
        </div>
      ) : null}

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-[var(--color-muted)] hover:text-white select-none">
          Why this is a setup
        </summary>
        <ul className="mt-2 space-y-1.5 list-disc pl-5 text-[var(--color-muted)]">
          {s.why.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      </details>
    </Card>
  );
}

function MiniStat({
  label,
  value,
  valueClass = "",
  blur = false,
}: {
  label: string;
  value: string;
  valueClass?: string;
  blur?: boolean;
}) {
  return (
    <div className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-2 py-2">
      <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </div>
      <div className={`text-sm font-semibold ${valueClass}`}>
        <BlurValue active={blur}>{value}</BlurValue>
      </div>
    </div>
  );
}

function PlanRow({ label, text }: { label: string; text: string }) {
  return (
    <div className="flex gap-2">
      <span className="shrink-0 w-12 font-bold text-[11px] uppercase tracking-wide text-[var(--color-muted)] pt-0.5">
        {label}
      </span>
      <span>{text}</span>
    </div>
  );
}
