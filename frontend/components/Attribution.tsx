"use client";

import {
  AttributionResponse,
  AttrCohort,
  AttrNumericFeature,
} from "@/lib/api";
import { Card, EmptyState } from "./ui";
import { InfoTip } from "./InfoTip";

const PROFIT = "#28c08a";
const LOSS = "#f0556d";
const MUTED = "#8a97b1";

function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return `${(v * 100).toFixed(digits)}%`;
}

function money(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  const sign = v < 0 ? "-" : v > 0 ? "+" : "";
  return `${sign}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function pnlColor(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return MUTED;
  return v > 0 ? PROFIT : LOSS;
}

// Blend from loss-red (0%) through muted (50%) to profit-green (100%).
function rateColor(rate: number): string {
  if (rate >= 0.5) return PROFIT;
  return LOSS;
}

function CohortTable({ title, rows }: { title: string; rows: AttrCohort[] }) {
  if (!rows.length) return null;
  return (
    <Card className="p-4">
      <h3 className="font-semibold text-sm mb-2">{title}</h3>
      <div className="space-y-2">
        {rows.map((r) => {
          const [lo, hi] = r.win_rate_ci;
          return (
            <div key={r.key} className="text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate pr-2 capitalize">{r.key}</span>
                <span
                  className="font-semibold shrink-0"
                  style={{ color: pnlColor(r.avg_pnl) }}
                >
                  {money(r.avg_pnl)}
                  <span className="text-[var(--color-muted)] font-normal">/trade</span>
                </span>
              </div>
              <div className="mt-1 flex items-center gap-2 text-[11px] text-[var(--color-muted)]">
                <span className="font-mono" style={{ color: rateColor(r.win_rate) }}>
                  {pct(r.win_rate)} win
                </span>
                <span>
                  CI {pct(lo)}–{pct(hi)}
                </span>
                <span className="ml-auto">
                  {r.wins}/{r.n}
                  {r.calibration_gap !== null ? (
                    <span
                      className="ml-2"
                      title="Realized win rate minus the model's average predicted win prob. Positive = we beat the model's expectation."
                    >
                      cal {r.calibration_gap > 0 ? "+" : ""}
                      {pct(r.calibration_gap)}
                    </span>
                  ) : null}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function TercileStrip({ f }: { f: AttrNumericFeature }) {
  if (!f.terciles.length) return null;
  return (
    <div className="flex gap-0.5">
      {f.terciles.map((t) => (
        <div
          key={t.band}
          title={`${t.band}: ${(t.range[0]).toLocaleString()}–${(t.range[1]).toLocaleString()} · ${pct(
            t.win_rate
          )} win · ${money(t.avg_pnl)}/trade (n=${t.n})`}
          className="h-5 flex-1 rounded-sm flex items-center justify-center text-[9px] font-semibold"
          style={{
            backgroundColor: `${pnlColor(t.avg_pnl)}2a`,
            color: pnlColor(t.avg_pnl),
          }}
        >
          {pct(t.win_rate)}
        </div>
      ))}
    </div>
  );
}

function NumericFeatures({ features }: { features: AttrNumericFeature[] }) {
  if (!features.length) return null;
  return (
    <Card className="p-4">
      <h3 className="font-semibold text-sm mb-2">
        Feature → outcome
        <InfoTip text="Correlation of each entry feature with realized P&L (Pearson r, with a 95% CI). A ★ means the CI excludes zero - the association is unlikely to be pure noise at the current sample. The strip shows win rate across low→mid→high thirds of that feature." />
      </h3>
      <div className="space-y-2.5">
        {features.map((f) => {
          const cp = f.corr_pnl;
          return (
            <div key={f.feature} className="text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate pr-2">
                  {cp?.significant ? (
                    <span style={{ color: PROFIT }} className="mr-1">
                      ★
                    </span>
                  ) : null}
                  {f.label}
                </span>
                <span className="shrink-0 font-mono text-xs">
                  {cp ? (
                    <span
                      style={{
                        color: cp.significant
                          ? cp.r > 0
                            ? PROFIT
                            : LOSS
                          : MUTED,
                      }}
                    >
                      r={cp.r > 0 ? "+" : ""}
                      {cp.r.toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-[var(--color-muted)]">-</span>
                  )}
                  <span className="text-[var(--color-muted)] ml-2">n={f.n}</span>
                </span>
              </div>
              <div className="mt-1">
                <TercileStrip f={f} />
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function Calibration({ report }: { report: AttributionResponse }) {
  const c = report.calibration;
  if (!c.buckets.length) return null;
  return (
    <Card className="p-4">
      <h3 className="font-semibold text-sm mb-2">
        Calibration
        <InfoTip text="Is the model's predicted win probability honest? Each row compares the average predicted win prob in a bucket against the win rate actually realized there. Close = well-calibrated." />
      </h3>
      <div className="text-[11px] text-[var(--color-muted)] mb-2">
        Overall predicted {pct(c.avg_predicted, 0)} vs realized{" "}
        <span style={{ color: rateColor(c.realized_win_rate ?? 0) }}>
          {pct(c.realized_win_rate, 0)}
        </span>{" "}
        ({c.n} graded)
      </div>
      <div className="space-y-1.5">
        {c.buckets.map((b) => (
          <div
            key={`${b.range[0]}-${b.range[1]}`}
            className="flex items-center justify-between text-sm"
          >
            <span className="text-[var(--color-muted)] font-mono text-xs">
              {pct(b.range[0])}–{pct(b.range[1])}
            </span>
            <span className="flex items-center gap-3">
              <span className="text-[var(--color-muted)] text-xs">
                pred {pct(b.avg_predicted)}
              </span>
              <span
                className="font-semibold"
                style={{ color: rateColor(b.realized_win_rate) }}
              >
                real {pct(b.realized_win_rate)}
              </span>
              <span className="text-[var(--color-muted)] text-xs w-10 text-right">
                n={b.n}
              </span>
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Counterfactual({ report }: { report: AttributionResponse }) {
  const rows = report.counterfactual.filter((c) => c.opened || c.skipped);
  if (!rows.length) return null;
  return (
    <Card className="p-4">
      <h3 className="font-semibold text-sm mb-2">
        Gate check: opened vs skipped
        <InfoTip text="For each strategy, the share of setups whose underlying moved favorably (direction-adjusted) over the next 5 days - comparing the ones we traded against the ones the gate skipped. If skipped setups moved up about as often as opened ones, the gate may be rejecting winners." />
      </h3>
      <div className="space-y-2">
        {rows.map((c) => (
          <div key={c.strategy} className="text-sm">
            <div className="capitalize mb-0.5">{c.strategy}</div>
            <div className="flex items-center gap-4 text-[11px] text-[var(--color-muted)]">
              <span>
                opened{" "}
                {c.opened ? (
                  <span style={{ color: rateColor(c.opened.up_rate) }}>
                    {pct(c.opened.up_rate)} up
                  </span>
                ) : (
                  "-"
                )}
                {c.opened ? ` (n=${c.opened.n})` : ""}
              </span>
              <span>
                skipped{" "}
                {c.skipped ? (
                  <span style={{ color: rateColor(c.skipped.up_rate) }}>
                    {pct(c.skipped.up_rate)} up
                  </span>
                ) : (
                  "-"
                )}
                {c.skipped ? ` (n=${c.skipped.n})` : ""}
              </span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function Attribution({ report }: { report: AttributionResponse | null }) {
  if (!report) return null;

  return (
    <div className="mb-8">
      <div className="mb-3 flex items-baseline gap-2">
        <h2 className="font-semibold">Which setup types win?</h2>
        <span className="text-[11px] text-[var(--color-muted)]">
          {report.graded_trades} closed trade{report.graded_trades === 1 ? "" : "s"}
        </span>
        <InfoTip text="Breaks closed trades into buckets (strategy, conviction, etc.) and shows which ones make money. Small samples are labeled so you don't over-trust them." />
      </div>

      {report.graded_trades === 0 ? (
        <EmptyState
          title="No graded trades yet."
          hint="Attribution appears once trades close and their outcomes are labeled. The journal is already recording every decision (including the ones the gate skipped)."
        />
      ) : (
        <>
          {report.notes.length ? (
            <div className="mb-3 rounded-lg border border-[#f0a85b]/30 bg-[#f0a85b]/5 px-3 py-2 text-[11px] leading-relaxed text-[var(--color-muted)]">
              {report.notes.map((n, i) => (
                <div key={i}>{n}</div>
              ))}
            </div>
          ) : null}

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(report.cohorts).map(([key, rows]) =>
              rows.length ? (
                <CohortTable
                  key={key}
                  title={report.cohort_labels[key] ?? key}
                  rows={rows}
                />
              ) : null
            )}
            <NumericFeatures features={report.numeric_features} />
            <Calibration report={report} />
            <Counterfactual report={report} />
          </div>
        </>
      )}
    </div>
  );
}
