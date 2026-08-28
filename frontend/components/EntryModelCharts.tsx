"use client";

import { AttrNumericFeature, EntryModelCoefficient, EntryModelState } from "@/lib/api";
import { Card } from "./ui";

const PROFIT = "#28c08a";
const LOSS = "#f0556d";
const MUTED = "#8a97b1";

const SKIP_FEATURE = /wave|reddit|drift|mention|sentiment|trigger|run-?up|pump/i;

const LABEL: Record<string, string> = {
  "Book: earnings equity": "Earnings stock trades",
  "Book: earnings": "Earnings option trades",
  "Book: waves": "Wave trades",
  "Book: drift": "Drift trades",
  "Book: reddit": "Reddit trades",
  "Direction: bullish": "Bullish setups",
  "Direction: bearish": "Bearish setups",
  "Direction: neutral": "Neutral setups",
  "Conviction: high": "High-conviction names",
  "Conviction: medium": "Medium-conviction names",
  "Conviction: low": "Low-conviction names",
};

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

function niceLabel(c: EntryModelCoefficient): string {
  return LABEL[c.label] || c.label;
}

function status(model: EntryModelState | null | undefined): {
  title: string;
  detail: string;
  live: boolean;
} | null {
  if (!model) return null;
  if (model.enabled && model.applicable) {
    return {
      live: true,
      title: "Scoring new names",
      detail: `Learned from ${model.n} closed trades. Names it scores poorly get skipped.`,
    };
  }
  if (model.enabled) {
    return {
      live: false,
      title: "Not scoring yet",
      detail: model.reason || "Need more closed trades before the scorer can be trusted.",
    };
  }
  return {
    live: false,
    title: "Not scoring names",
    detail: "Still using the regular playbook only.",
  };
}

function splitWeights(model: EntryModelState | null | undefined) {
  const ranked = [...(model?.coefficients ?? [])]
    .filter((c) => Number.isFinite(c.weight) && Math.abs(c.weight) >= 0.15)
    .sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
  const helps = ranked.filter((c) => c.weight > 0).slice(0, 4);
  const hurts = ranked.filter((c) => c.weight < 0).slice(0, 4);
  return { helps, hurts };
}

function comparisons(features: AttrNumericFeature[] | null | undefined) {
  const rows: {
    label: string;
    highPct: number;
    lowPct: number;
    highWins: boolean;
    delta: number;
  }[] = [];
  for (const f of features ?? []) {
    if (SKIP_FEATURE.test(f.feature) || SKIP_FEATURE.test(f.label)) continue;
    const low = f.terciles.find((t) => t.band === "low");
    const high = f.terciles.find((t) => t.band === "high");
    if (!low || !high || low.n < 5 || high.n < 5) continue;
    const delta = high.win_rate - low.win_rate;
    if (!Number.isFinite(delta) || Math.abs(delta) < 0.06) continue;
    rows.push({
      label: f.label,
      highPct: high.win_rate,
      lowPct: low.win_rate,
      highWins: delta > 0,
      delta: Math.abs(delta),
    });
  }
  return rows.sort((a, b) => b.delta - a.delta).slice(0, 5);
}

function WinBar({ value, color }: { value: number; color: string }) {
  return (
    <div>
      <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-edge)]">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.max(4, Math.min(100, value * 100))}%`, background: color }}
        />
      </div>
      <div className="mt-0.5 text-[11px] tabular-nums text-[var(--color-muted)]">
        {pct(value)} won
      </div>
    </div>
  );
}

export function EntryModelCharts({
  model,
  features,
}: {
  model: EntryModelState | null | undefined;
  features: AttrNumericFeature[] | null | undefined;
}) {
  const st = status(model);
  const { helps, hurts } = splitWeights(model);
  const rows = comparisons(features);
  if (!st && !rows.length) return null;

  return (
    <Card className="mb-8 p-4">
      <h2 className="text-lg font-semibold tracking-tight">How names get picked</h2>
      {st ? (
        <p className="mt-1 text-sm leading-relaxed text-[var(--color-muted)]">
          <span
            className="font-semibold"
            style={{ color: st.live ? PROFIT : MUTED }}
          >
            {st.title}.
          </span>{" "}
          {st.detail}
        </p>
      ) : null}

      {helps.length || hurts.length ? (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">
              Helped winners
            </div>
            {helps.length ? (
              <ul className="space-y-1">
                {helps.map((c) => (
                  <li key={c.feature} className="text-sm text-[#c9d2e3]">
                    {niceLabel(c)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[var(--color-muted)]">Nothing clear yet.</p>
            )}
          </div>
          <div>
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">
              Showed up more in losers
            </div>
            {hurts.length ? (
              <ul className="space-y-1">
                {hurts.map((c) => (
                  <li key={c.feature} className="text-sm text-[#c9d2e3]">
                    {niceLabel(c)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[var(--color-muted)]">Nothing clear yet.</p>
            )}
          </div>
        </div>
      ) : null}

      {rows.length ? (
        <div className="mt-5">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">
            On closed trades
          </div>
          <p className="mb-3 text-sm text-[var(--color-muted)]">
            Each row is one factor at entry. Compare the bottom third vs the top
            third — whichever bar is longer won more often.
          </p>
          <div className="space-y-3">
            {rows.map((r) => (
              <div key={r.label}>
                <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm text-[#e8edf7]">{r.label}</span>
                  <span className="text-[11px] text-[var(--color-muted)]">
                    {r.highWins ? "higher values won more" : "lower values won more"}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <WinBar value={r.lowPct} color={r.highWins ? MUTED : PROFIT} />
                  <WinBar value={r.highPct} color={r.highWins ? PROFIT : MUTED} />
                </div>
                <div className="mt-0.5 grid grid-cols-2 gap-3 text-[10px] text-[var(--color-muted)]">
                  <span>Lower</span>
                  <span>Higher</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
