"use client";

import {
  ExecutionResponse,
  SignalCohort,
  SignalGroup,
} from "@/lib/api";
import { Card } from "./ui";
import { InfoTip } from "./InfoTip";

const PROFIT = "#28c08a";
const LOSS = "#f0556d";
const MUTED = "#8a97b1";
const ACCENT = "#5b8cff";
const WARN = "#f0a85b";

function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

function signed(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = v > 0 ? "+" : "";
  return `${s}${(v * 100).toFixed(digits)}%`;
}

function ratio(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(2);
}

function moveColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return MUTED;
  return v > 0 ? PROFIT : v < 0 ? LOSS : MUTED;
}

function Metric({
  label,
  value,
  valueColor,
  sub,
  info,
}: {
  label: string;
  value: string;
  valueColor?: string;
  sub?: string;
  info?: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2.5">
      <div className="flex items-center text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
        {label}
        {info ? <InfoTip text={info} /> : null}
      </div>
      <div
        className="mt-0.5 text-xl font-semibold tabular-nums"
        style={{ color: valueColor ?? "#e8edf7" }}
      >
        {value}
      </div>
      {sub ? (
        <div className="text-[11px] text-[var(--color-muted)] mt-0.5">{sub}</div>
      ) : null}
    </div>
  );
}

function SignalRow({ c }: { c: SignalCohort }) {
  return (
    <tr className="border-t border-[var(--color-edge)]">
      <td className="py-2 pr-3 font-medium capitalize">{c.key}</td>
      <td className="py-2 pr-3 tabular-nums">{c.n}</td>
      <td className="py-2 pr-3 tabular-nums">
        {pct(c.hit_rate)}
        <span className="ml-1 text-[10px] text-[var(--color-muted)]">
          [{pct(c.hit_rate_ci[0])}–{pct(c.hit_rate_ci[1])}]
        </span>
      </td>
      <td className="py-2 pr-3 tabular-nums" style={{ color: moveColor(c.avg_fav_move_5d) }}>
        {signed(c.avg_fav_move_5d)}
      </td>
      <td className="py-2 tabular-nums text-[var(--color-muted)]">
        {signed(c.avg_fav_move_1d)}
      </td>
    </tr>
  );
}

function OpenedVsSkipped({
  opened,
  skipped,
}: {
  opened: SignalGroup | null;
  skipped: SignalGroup | null;
}) {
  if (!opened && !skipped) return null;
  // The gate is doing its job when the trades we OPENED had a better forward
  // move than the ones we SKIPPED. If skipped ≈ opened, we're leaving edge behind.
  const delta =
    opened && skipped
      ? opened.avg_fav_move_5d - skipped.avg_fav_move_5d
      : null;
  return (
    <div className="mt-3 rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2.5">
      <div className="flex items-center text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-1.5">
        Gate quality · opened vs. skipped
        <InfoTip text="The average +5d favorable move of the signals we OPENED vs. the ones we SKIPPED. If opened is clearly higher, the entry gate is picking the better leans. If they're similar (or skipped is higher), the gate is rejecting winners." />
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
        <span>
          <span className="text-[var(--color-muted)]">Opened</span>{" "}
          <span className="font-semibold tabular-nums" style={{ color: moveColor(opened?.avg_fav_move_5d) }}>
            {signed(opened?.avg_fav_move_5d)}
          </span>
          <span className="text-[11px] text-[var(--color-muted)]"> ({opened?.n ?? 0}, hit {pct(opened?.hit_rate)})</span>
        </span>
        <span>
          <span className="text-[var(--color-muted)]">Skipped</span>{" "}
          <span className="font-semibold tabular-nums" style={{ color: moveColor(skipped?.avg_fav_move_5d) }}>
            {signed(skipped?.avg_fav_move_5d)}
          </span>
          <span className="text-[11px] text-[var(--color-muted)]"> ({skipped?.n ?? 0}, hit {pct(skipped?.hit_rate)})</span>
        </span>
        {delta !== null ? (
          <span className="text-[11px]" style={{ color: delta > 0 ? PROFIT : LOSS }}>
            {delta > 0 ? "gate adds" : "gate rejects winners"} {signed(Math.abs(delta))}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function SignalVintage({ weeks }: { weeks: ExecutionResponse["signal_weeks"] }) {
  const withData = weeks.filter((w) => w.n > 0);
  if (withData.length < 2) return null;
  const maxAbs = Math.max(
    0.01,
    ...withData.map((w) => Math.abs(w.avg_fav_move_5d ?? 0))
  );
  return (
    <div className="mt-4">
      <div className="flex items-center text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-2">
        Signal quality by vintage (+5d)
        <InfoTip text="The average +5d favorable move of every signal that fired that week — keyed on when the signal was generated, not when the trade closed. This is the cleanest read of whether the signals themselves are getting better over time, without slow-closing strategies hiding in close-date buckets." />
      </div>
      <div className="flex items-end gap-1.5 h-20">
        {weeks.map((w) => {
          const v = w.avg_fav_move_5d;
          const h = v === null ? 0 : Math.round((Math.abs(v) / maxAbs) * 100);
          return (
            <div key={w.week_start} className="flex-1 flex flex-col items-center justify-end h-full">
              <div className="w-full flex flex-col justify-end items-center h-full">
                <div
                  className="w-full rounded-sm"
                  style={{
                    height: `${h}%`,
                    minHeight: v === null ? 0 : 2,
                    backgroundColor: v === null ? "transparent" : moveColor(v),
                    opacity: 0.85,
                  }}
                  title={
                    v === null
                      ? `${w.label}: no signals`
                      : `${w.label}: ${signed(v)} avg +5d (n=${w.n}, hit ${pct(w.hit_rate)})`
                  }
                />
              </div>
              <div className="text-[9px] text-[var(--color-muted)] mt-1 whitespace-nowrap">
                {w.label.split(" ")[1] ?? w.label}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ExecutionQuality({ report }: { report: ExecutionResponse | null }) {
  if (!report || report.graded_signals === 0) return null;

  const sq = report.signal_quality;
  const et = report.entry_timing;
  const ec = report.exit_capture.summary;
  const worst = report.exit_capture.worst_giveback;

  return (
    <div className="mb-8">
      <div className="mb-3 flex items-baseline gap-2">
        <h2 className="font-semibold">Signal vs. execution</h2>
        <span className="text-[11px] text-[var(--color-muted)]">
          {report.graded_signals} graded signal{report.graded_signals === 1 ? "" : "s"}
        </span>
        <InfoTip text="Realized P&L blends three things: was the lean right, did we enter on time, and did we exit on time. This splits them apart so a loss can be diagnosed — a bad signal, a chased entry, or a mistimed exit are very different problems." />
      </div>

      <Card className="p-4">
        {/* The three axes as headline metrics. */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Metric
            label="Signal lean (+5d)"
            value={signed(sq.overall?.avg_fav_move_5d)}
            valueColor={moveColor(sq.overall?.avg_fav_move_5d)}
            sub={`${pct(sq.overall?.hit_rate)} hit · ${sq.overall?.n ?? 0} decisions`}
            info="Across ALL decisions (opened and skipped): the underlying's direction-adjusted move 5 trading days after the call. Measures the signal itself, independent of how we traded it."
          />
          <Metric
            label="Entry timing"
            value={
              et.avg_pre_entry_fav_move === null
                ? "—"
                : signed(et.avg_pre_entry_fav_move)
            }
            valueColor={
              et.avg_pre_entry_fav_move === null
                ? undefined
                : et.avg_pre_entry_fav_move > 0.02
                ? WARN
                : PROFIT
            }
            sub={
              et.median_lag_days === null
                ? `${et.n} trades`
                : `${et.median_lag_days}d median lag · chased ${pct(et.chased_rate)}`
            }
            info="How much the underlying had already moved our way between the decision and our fill. Positive = we entered after the move started (chasing); near-zero or negative = we were early. 'Chased' = filled after a >2% favorable move."
          />
          <Metric
            label="Exit capture"
            value={ratio(ec.median_capture_ratio)}
            valueColor={
              ec.median_capture_ratio === null
                ? undefined
                : ec.median_capture_ratio >= 0.6
                ? PROFIT
                : ec.median_capture_ratio >= 0.35
                ? WARN
                : LOSS
            }
            sub={
              ec.n === 0
                ? "no directional exits yet"
                : `kept of peak · left >½ on table ${pct(ec.left_on_table_rate)}`
            }
            info="For directional trades (waves/drift/reddit): of the maximum favorable move the underlying reached while we held it (MFE), how much did we still have at exit? 1.0 = exited at the peak; 0.5 = gave back half. Below ~0.5 means exits are late. Median across closed trades."
          />
        </div>

        {ec.n > 0 && (ec.avg_mfe !== null || ec.avg_mae !== null) ? (
          <div className="mt-2 text-[11px] text-[var(--color-muted)]">
            Avg peak available (MFE){" "}
            <span style={{ color: PROFIT }}>{signed(ec.avg_mfe)}</span> · avg worst
            drawdown held through (MAE){" "}
            <span style={{ color: LOSS }}>{signed(ec.avg_mae)}</span>
            {ec.avg_hold_days !== null ? ` · ${ec.avg_hold_days}d avg hold` : ""}
          </div>
        ) : null}

        <OpenedVsSkipped
          opened={sq.opened_vs_skipped.opened}
          skipped={sq.opened_vs_skipped.skipped}
        />

        {sq.by_strategy.length ? (
          <div className="mt-4 overflow-x-auto">
            <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-1">
              Signal lean by strategy
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[var(--color-muted)] text-xs uppercase tracking-wide">
                  <th className="py-1 pr-3">Strategy</th>
                  <th className="py-1 pr-3">n</th>
                  <th className="py-1 pr-3">Hit rate</th>
                  <th className="py-1 pr-3">Avg +5d</th>
                  <th className="py-1">Avg +1d</th>
                </tr>
              </thead>
              <tbody>
                {sq.by_strategy.map((c) => (
                  <SignalRow key={c.key} c={c} />
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {worst.length ? (
          <div className="mt-4">
            <div className="flex items-center text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-1">
              Biggest give-backs (exit sooner?)
              <InfoTip text="Closed directional trades where the underlying reached a big favorable move (MFE) that we then handed back before exiting. These are the concrete 'we should have taken profit earlier' cases." />
            </div>
            <div className="space-y-1">
              {worst.map((w) => (
                <div
                  key={w.signal_id ?? w.ticker}
                  className="flex items-center justify-between text-xs border-t border-[var(--color-edge)] py-1.5"
                >
                  <span className="font-medium">
                    {w.ticker}
                    <span className="ml-2 text-[10px] uppercase text-[var(--color-muted)]">
                      {w.strategy}
                    </span>
                  </span>
                  <span className="tabular-nums text-[var(--color-muted)]">
                    peak <span style={{ color: PROFIT }}>{signed(w.mfe)}</span> → kept{" "}
                    <span style={{ color: moveColor(w.realized_fav_move) }}>
                      {signed(w.realized_fav_move)}
                    </span>{" "}
                    · gave back{" "}
                    <span style={{ color: LOSS }}>{signed(w.gave_back)}</span>
                    {w.capture_ratio !== null ? ` (${ratio(w.capture_ratio)}×)` : ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <SignalVintage weeks={report.signal_weeks} />

        {report.notes.length ? (
          <p className="mt-3 text-[10px] leading-relaxed text-[var(--color-muted)]">
            {report.notes.join(" ")}
          </p>
        ) : null}
      </Card>
    </div>
  );
}
