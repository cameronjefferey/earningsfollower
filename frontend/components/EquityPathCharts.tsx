"use client";

import {
  Area,
  ComposedChart,
  Legend,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  EquityPathEvent,
  EquityPathPoint,
  EquityPathResponse,
} from "@/lib/api";
import { Card, Stat } from "./ui";
import { InfoTip } from "./InfoTip";

const PROFIT = "#28c08a";
const LOSS = "#f0556d";
const ACCENT = "#5b8cff";
const WARN = "#f0a85b";
const MUTED = "#8a97b1";
const ADD = "#b06bff";

const KIND_COLOR: Record<string, string> = {
  retire: PROFIT,
  guard: ACCENT,
  fix: WARN,
  add: ADD,
};

function money(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  const sign = v < 0 ? "-" : v > 0 ? "+" : "";
  return `${sign}$${Math.abs(v).toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })}`;
}

function dollars(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return `$${Math.round(v).toLocaleString()}`;
}

function axisMoney(v: number): string {
  if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(0)}k`;
  return `$${Math.round(v)}`;
}

function monthTick(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return `${(v * 100).toFixed(0)}%`;
}

function pnlClass(v: number | null | undefined): string {
  if (v == null || v === 0) return "";
  return v > 0 ? "text-[#28c08a]" : "text-[#f0556d]";
}

function PathTooltip({
  active,
  payload,
  label,
  events,
  showAllowed,
}: {
  active?: boolean;
  payload?: Array<{ dataKey?: string; value?: number; color?: string }>;
  label?: string;
  events: EquityPathEvent[];
  showAllowed: boolean;
}) {
  if (!active || !payload?.length || !label) return null;
  const byKey = new Map(payload.map((p) => [p.dataKey, p]));
  const marks = events.filter((e) => e.chart_date === label);
  return (
    <div className="rounded-lg border border-[var(--color-edge)] bg-[#121826] px-3 py-2 text-xs text-[#e8edf7] shadow-xl">
      <div className="mb-1 font-semibold">{monthTick(label)}</div>
      {byKey.has("actual") ? (
        <div style={{ color: ACCENT }}>
          Actual {dollars(byKey.get("actual")?.value)}
        </div>
      ) : null}
      {showAllowed && byKey.has("allowed") ? (
        <div style={{ color: PROFIT }}>
          Today&apos;s book {dollars(byKey.get("allowed")?.value)}
        </div>
      ) : null}
      {marks.map((e) => (
        <div key={e.title} className="mt-1.5 max-w-56 leading-snug">
          <span style={{ color: KIND_COLOR[e.kind] ?? WARN }}>{e.title}</span>
          <div className="text-[var(--color-muted)]">{e.detail}</div>
        </div>
      ))}
    </div>
  );
}

function domainOf(points: EquityPathPoint[], keys: Array<"actual" | "allowed">) {
  const vals = points.flatMap((p) =>
    keys.map((k) => p[k]).filter((v): v is number => typeof v === "number")
  );
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const pad = (max - min) * 0.12 || max * 0.05;
  return [min - pad, max + pad] as [number, number];
}

function EquityChart({
  points,
  events,
  showAllowed,
  actualStroke = ACCENT,
}: {
  points: EquityPathPoint[];
  events: EquityPathEvent[];
  showAllowed: boolean;
  actualStroke?: string;
}) {
  const keys: Array<"actual" | "allowed"> = showAllowed
    ? ["actual", "allowed"]
    : ["actual"];
  const domain = domainOf(points, keys);
  const byDate = new Map(points.map((p) => [p.date, p]));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart data={points} margin={{ top: 12, right: 12, left: -4, bottom: 0 }}>
        <defs>
          <linearGradient id="equityActualFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={actualStroke} stopOpacity={0.28} />
            <stop offset="100%" stopColor={actualStroke} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="date"
          tick={{ fill: MUTED, fontSize: 11 }}
          axisLine={{ stroke: "#243049" }}
          tickLine={false}
          minTickGap={48}
          tickFormatter={monthTick}
        />
        <YAxis
          domain={domain}
          tick={{ fill: MUTED, fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={52}
          tickFormatter={axisMoney}
        />
        <Tooltip
          cursor={{ stroke: "#243049" }}
          content={
            <PathTooltip events={events} showAllowed={showAllowed} />
          }
        />
        {showAllowed ? (
          <Legend
            wrapperStyle={{ fontSize: 12, color: MUTED }}
            formatter={(value) =>
              value === "actual" ? "What happened" : "Today's book only"
            }
          />
        ) : null}
        {events.map((e) => (
          <ReferenceLine
            key={`${e.kind}-${e.date}`}
            x={e.chart_date}
            stroke={KIND_COLOR[e.kind] ?? WARN}
            strokeDasharray="3 3"
            strokeOpacity={0.7}
          />
        ))}
        {showAllowed ? (
          <Line
            type="monotone"
            dataKey="actual"
            stroke={MUTED}
            strokeWidth={1.5}
            strokeDasharray="5 4"
            dot={false}
            isAnimationActive={false}
          />
        ) : (
          <Area
            type="monotone"
            dataKey="actual"
            stroke={actualStroke}
            strokeWidth={2}
            fill="url(#equityActualFill)"
            isAnimationActive={false}
          />
        )}
        {showAllowed ? (
          <Line
            type="monotone"
            dataKey="allowed"
            stroke={PROFIT}
            strokeWidth={2.25}
            dot={false}
            isAnimationActive={false}
          />
        ) : null}
        {!showAllowed
          ? events.map((e) => {
              const pt = byDate.get(e.chart_date);
              if (!pt) return null;
              return (
                <ReferenceDot
                  key={`dot-${e.kind}-${e.date}`}
                  x={e.chart_date}
                  y={pt.actual}
                  r={4}
                  fill={KIND_COLOR[e.kind] ?? WARN}
                  stroke="#0b0f17"
                  strokeWidth={1.5}
                  isFront
                />
              );
            })
          : null}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function EquityPathCharts({ report }: { report: EquityPathResponse | null }) {
  if (!report || report.points.length < 2) return null;

  const actualEnd = report.latest_actual;
  const allowedEnd = report.latest_allowed;
  const start = report.starting_equity;
  const actualDelta = actualEnd != null ? actualEnd - start : null;
  const allowedDelta = allowedEnd != null ? allowedEnd - start : null;
  const actualColor =
    actualDelta == null ? ACCENT : actualDelta >= 0 ? PROFIT : LOSS;

  return (
    <div className="mb-8 space-y-4">
      <Card className="p-4">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">
              Account value
              <InfoTip text={report.window_note} />
            </h2>
            <p className="mt-1 max-w-2xl text-sm text-[var(--color-muted)] leading-relaxed">
              Paper account close, marked with the policy changes. Retires are
              green — that&apos;s when we stopped funding a losing book.
            </p>
          </div>
          <div className="text-right">
            <div className="text-xl font-semibold tabular" style={{ color: actualColor }}>
              {dollars(actualEnd)}
            </div>
            <div className={`text-xs tabular ${pnlClass(actualDelta)}`}>
              {money(actualDelta)} from {dollars(start)}
            </div>
          </div>
        </div>
        <EquityChart
          points={report.points}
          events={report.events}
          showAllowed={false}
          actualStroke={actualColor}
        />
        <ol className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {report.events.map((e) => (
            <li
              key={`${e.kind}-${e.date}`}
              className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2"
            >
              <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: KIND_COLOR[e.kind] ?? WARN }}
                />
                {monthTick(e.chart_date)}
                <span className="normal-case tracking-normal">· {e.kind}</span>
              </div>
              <div className="mt-0.5 text-sm font-medium leading-snug">{e.title}</div>
              <div className="mt-0.5 text-xs text-[var(--color-muted)] leading-snug">
                {e.detail}
              </div>
            </li>
          ))}
        </ol>
        {report.actual_source === "journal" ? (
          <p className="mt-3 text-[11px] text-[var(--color-muted)]">
            Alpaca history wasn&apos;t available, so this line is reconstructed
            from closed-trade P&amp;L (no open marks).
          </p>
        ) : null}
      </Card>

      {report.all.n > 0 ? (
      <Card className="p-4">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">
              Had we only run today&apos;s book
              <InfoTip text="Closed trades only. Earnings sell-vol, earnings stock, and 5-day losers stay in. Reddit, drift, and waves are removed. Open positions are not marked." />
            </h2>
            <p className="mt-1 max-w-2xl text-sm text-[var(--color-muted)] leading-relaxed">
              Start at {dollars(start)}. Add closed P&amp;L from{" "}
              {report.allowed_labels.join(" + ") || "the live books"} only.
              Still some losing trades — that&apos;s the remaining strategy,
              not a fantasy of all winners.
            </p>
          </div>
          <div className="text-right">
            <div
              className="text-xl font-semibold tabular"
              style={{ color: (allowedDelta ?? 0) >= 0 ? PROFIT : LOSS }}
            >
              {dollars(allowedEnd)}
            </div>
            <div className={`text-xs tabular ${pnlClass(allowedDelta)}`}>
              {money(allowedDelta)} closed P&amp;L
            </div>
          </div>
        </div>
        <EquityChart
          points={report.points}
          events={report.events}
          showAllowed
        />
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          <Stat
            label="Today's book"
            value={money(report.allowed.total_pnl)}
            valueClass={pnlClass(report.allowed.total_pnl)}
            sub={`${report.allowed.wins}/${report.allowed.n} closed · ${pct(report.allowed.win_rate)} wins`}
          />
          <Stat
            label="Retired books"
            value={money(report.retired.total_pnl)}
            valueClass={pnlClass(report.retired.total_pnl)}
            sub={`${report.retired.wins}/${report.retired.n} closed · reddit, drift, waves`}
            info="P&L we would not have taken if today's flags had been on from day one."
          />
          <Stat
            label="Whole journal"
            value={money(report.all.total_pnl)}
            valueClass={pnlClass(report.all.total_pnl)}
            sub={`${report.all.wins}/${report.all.n} closed`}
          />
        </div>
        {report.by_book.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
                  <th className="pb-1 pr-3 font-medium">Book</th>
                  <th className="pb-1 pr-3 font-medium">In today&apos;s book?</th>
                  <th className="pb-1 pr-3 font-medium">Closed</th>
                  <th className="pb-1 pr-3 font-medium">Win rate</th>
                  <th className="pb-1 font-medium">P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {report.by_book.map((b) => (
                  <tr key={b.book} className="border-t border-[var(--color-edge)]">
                    <td className="py-1.5 pr-3">{b.label}</td>
                    <td className="py-1.5 pr-3" style={{ color: b.allowed ? PROFIT : MUTED }}>
                      {b.allowed ? "yes" : "retired"}
                    </td>
                    <td className="py-1.5 pr-3 tabular">
                      {b.wins}/{b.n}
                    </td>
                    <td className="py-1.5 pr-3 tabular">{pct(b.win_rate)}</td>
                    <td className={`py-1.5 tabular ${pnlClass(b.total_pnl)}`}>
                      {money(b.total_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
      ) : (
        <p className="text-xs text-[var(--color-muted)]">
          Closed-trade P&amp;L isn&apos;t in this database yet, so we can&apos;t
          rebuild the &quot;today&apos;s book only&quot; line. Account value
          above is still the live Alpaca close.
        </p>
      )}
    </div>
  );
}
