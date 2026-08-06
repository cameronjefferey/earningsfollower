"use client";

import { ProgressResponse, ProgressWeek } from "@/lib/api";
import { Card } from "./ui";
import { InfoTip } from "./InfoTip";

const PROFIT = "#28c08a";
const LOSS = "#f0556d";
const MUTED = "#8a97b1";
const WARN = "#f0a85b";

function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

function money(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v < 0 ? "-" : v > 0 ? "+" : "";
  return `${sign}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

const STATUS_META: Record<string, { label: string; color: string }> = {
  improved: { label: "got better", color: PROFIT },
  regressed: { label: "got worse", color: LOSS },
  flat: { label: "same", color: MUTED },
};

// A signed delta chip. `goodWhenNegative` flips the color logic (used for the
// calibration gap, where smaller is better).
function Delta({
  value,
  kind,
  goodWhenNegative = false,
}: {
  value: number | null | undefined;
  kind: "pct" | "count";
  goodWhenNegative?: boolean;
}) {
  if (value === null || value === undefined || value === 0) return null;
  const good = goodWhenNegative ? value < 0 : value > 0;
  const arrow = value > 0 ? "▲" : "▼";
  const text = kind === "pct" ? pct(Math.abs(value)) : `${Math.abs(value)}`;
  return (
    <span className="ml-1 text-[10px]" style={{ color: good ? PROFIT : LOSS }}>
      {arrow}
      {text}
    </span>
  );
}

function VerdictBanner({ report }: { report: ProgressResponse }) {
  const v = report.verdict;
  const color = v.learning === true ? PROFIT : v.learning === false ? LOSS : WARN;
  const label =
    v.learning === true
      ? "Getting sharper"
      : v.learning === false
      ? "Not clearly better yet"
      : "Too early to tell";
  return (
    <div
      className="rounded-lg border px-3 py-2 mb-3"
      style={{ borderColor: `${color}44`, backgroundColor: `${color}12` }}
    >
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold" style={{ color }}>
          {label}
        </span>
        {v.weeks_improved !== undefined ? (
          <span className="text-[11px] text-[var(--color-muted)]">
            {v.weeks_improved} better weeks · {v.weeks_regressed} worse
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-xs text-[#c9d2e3]">{v.summary}</p>
    </div>
  );
}

function WeekRow({ w }: { w: ProgressWeek }) {
  const c = w.cumulative;
  const nw = w.new_this_week;
  const meta = STATUS_META[w.status] ?? STATUS_META.flat;
  const empty = c.graded_trades === 0 && nw.closed === 0;
  return (
    <tr className="border-t border-[var(--color-edge)] align-top" style={{ opacity: empty ? 0.5 : 1 }}>
      <td className="py-2 pr-3 whitespace-nowrap font-semibold">{w.label}</td>
      <td className="py-2 pr-3">
        <span
          className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold border"
          style={{ color: meta.color, borderColor: `${meta.color}55`, backgroundColor: `${meta.color}1a` }}
        >
          {meta.label}
        </span>
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        {c.graded_trades}
        <Delta value={w.deltas?.graded_trades} kind="count" />
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        {pct(c.win_rate)}
        <Delta value={w.deltas?.win_rate} kind="pct" />
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        {pct(c.calibration_gap)}
        <Delta value={w.deltas?.calibration_gap} kind="pct" goodWhenNegative />
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        {c.significant_features}
        <Delta value={w.deltas?.significant_features} kind="count" />
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        {nw.closed ? (
          <span>
            {nw.closed} @ {pct(nw.win_rate)}{" "}
            <span style={{ color: (nw.avg_pnl ?? 0) >= 0 ? PROFIT : LOSS }}>
              {money(nw.total_pnl)}
            </span>
          </span>
        ) : (
          <span className="text-[var(--color-muted)]">—</span>
        )}
      </td>
      <td className="py-2 text-[var(--color-muted)]">
        <ul className="space-y-0.5">
          {w.changes.map((ch, i) => (
            <li key={i} className="leading-snug">
              {ch}
            </li>
          ))}
        </ul>
      </td>
    </tr>
  );
}

export function WeeklyProgress({ report }: { report: ProgressResponse | null }) {
  if (!report) return null;
  const anyData = report.weeks.some(
    (w) => w.cumulative.graded_trades > 0 || w.new_this_week.closed > 0
  );
  if (!anyData) return null;

  // Newest week first.
  const weeks = [...report.weeks].reverse();

  return (
    <div className="mb-8">
      <div className="mb-3 flex items-baseline gap-2">
        <h2 className="font-semibold">Week by week</h2>
        <InfoTip text="Each row is the paper book as of that week: how many trades had closed, win rate so far, whether our odds were honest, and what newly closed that week. Green arrows usually mean improvement (for 'odds miss', smaller is better)." />
      </div>

      <VerdictBanner report={report} />

      <Card className="p-4">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[var(--color-muted)] text-xs uppercase tracking-wide">
                <th className="py-2 pr-3">Week</th>
                <th className="py-2 pr-3">Trend</th>
                <th className="py-2 pr-3">
                  Closed
                  <InfoTip text="How many paper trades had finished and been scored by the end of this week." />
                </th>
                <th className="py-2 pr-3">
                  Win rate
                  <InfoTip text="Wins ÷ closed trades known by this week." />
                </th>
                <th className="py-2 pr-3">
                  Odds miss
                  <InfoTip text="How far our predicted win rate was from reality. Smaller is better — a green down arrow means we got more honest." />
                </th>
                <th className="py-2 pr-3">
                  Patterns
                  <InfoTip text="How many entry clues (like conviction or edge size) clearly line up with winners so far." />
                </th>
                <th className="py-2 pr-3">Closed this week</th>
                <th className="py-2">In plain English</th>
              </tr>
            </thead>
            <tbody>
              {weeks.map((w) => (
                <WeekRow key={w.week_start} w={w} />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
