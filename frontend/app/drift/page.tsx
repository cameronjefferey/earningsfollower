"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { api, DriftResponse, DriftSetup } from "@/lib/api";
import { Card, EmptyState, Spinner, ThemePill } from "@/components/ui";
import { InfoTip } from "@/components/InfoTip";
import { glossary } from "@/lib/glossary";
import { fmtDate, moveClass, pct, signedPct } from "@/lib/format";

export default function DriftPage() {
  const { data: session } = useSession();
  const isAdmin = Boolean(session?.isAdmin);
  const [lookbackDays, setLookbackDays] = useState(12);
  const [directionFilter, setDirectionFilter] = useState<"all" | "long" | "short">("all");
  const [data, setData] = useState<DriftResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .drift(lookbackDays)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [lookbackDays]);

  const setups = (data?.setups ?? []).filter(
    (s) => directionFilter === "all" || s.direction === directionFilter
  );

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Post-earnings drift</h1>
        <p className="text-sm text-[var(--color-muted)] mt-1 max-w-2xl">
          Stocks that just delivered a strong print (beat + up move, or miss + down
          move) tend to keep moving the same direction for ~5 trading days. These are
          the live setups where this stock&apos;s own history says the drift pays.
        </p>
      </div>

      {isAdmin ? <Playbook /> : null}

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
      </div>

      {loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState title="Couldn't reach the API." hint="Is the backend running?" />
      ) : setups.length === 0 ? (
        <EmptyState
          title="No live drift setups right now."
          hint="Setups appear after strong prints (beat + up move or miss + down move) on stocks whose history shows the drift continues. Widen the lookback, or check back after the next batch of reports."
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {setups.map((s) => (
            <SetupCard
              key={`${s.ticker}-${s.report_date}`}
              setup={s}
              showPlan={isAdmin}
            />
          ))}
        </div>
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
}: {
  setup: DriftSetup;
  showPlan: boolean;
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
            {plan ? <QualityBadge quality={plan.entry_quality} /> : null}
          </div>
          {s.name ? (
            <div className="text-sm text-[var(--color-muted)] mt-0.5">{s.name}</div>
          ) : null}
          <div className="text-sm text-[var(--color-muted)] mt-0.5">
            reported {fmtDate(s.report_date)} ·{" "}
            <span className={moveClass(s.move_pct)}>{signedPct(s.move_pct)}</span> on the
            print{s.beat ? " · beat" : " · miss"}
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
            {signedPct(s.history.avg_drift_5d_pct)}
          </div>
          <div className="text-xs text-[var(--color-muted)]">
            {pct(s.history.win_rate_5d, 0)} win · n={s.history.sample_size}
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
        />
        <MiniStat
          label="Days in / left"
          value={`${s.live.trading_days_in} / ${s.live.trading_days_left}`}
        />
        {plan ? (
          <MiniStat
            label="Stop level"
            value={s.live.stop_level !== null ? `$${s.live.stop_level}` : "—"}
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
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-2 py-2">
      <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </div>
      <div className={`text-sm font-semibold ${valueClass}`}>{value}</div>
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
