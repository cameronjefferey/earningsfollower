"use client";

import {
  AttributionResponse,
  ExecutionResponse,
  NarrativeResponse,
  ProgressResponse,
} from "@/lib/api";
import { Card } from "./ui";

const ACCENT = "#5b8cff";
const PROFIT = "#28c08a";
const WARN = "#f0a85b";
const LOSS = "#f0556d";

function money(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  const sign = v < 0 ? "-" : v > 0 ? "+" : "";
  return `${sign}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return `${(v * 100).toFixed(0)}%`;
}

/** Turn jargon-y narrative lines into something you can act on. */
function plainPoint(raw: string): string {
  return raw
    .replace(/\bcalibration gap\b/gi, "prediction miss")
    .replace(/\bwell-calibrated\b/gi, "honest about its odds")
    .replace(/\bunder-confident\b/gi, "winning more than it expected")
    .replace(/\bover-confident\b/gi, "winning less than it expected")
    .replace(/\bthe gate\b/gi, "our entry filter")
    .replace(/\brejecting winners\b/gi, "passing on setups that then worked")
    .replace(/\bgraded trades?\b/gi, "closed trades")
    .replace(/\bthin sample\b/gi, "small sample - take lightly")
    .replace(/\bCI\b/g, "likely range")
    .replace(/\bn=(\d+)/g, "($1 trades)")
    .replace(/\br=([+-]?\d+\.\d+)/g, "link strength $1");
}

function latestWeek(progress: ProgressResponse | null) {
  if (!progress?.weeks?.length) return null;
  const withData = [...progress.weeks]
    .reverse()
    .find(
      (w) =>
        w.cumulative.graded_trades > 0 || w.new_this_week.closed > 0
    );
  return withData ?? null;
}

function buildDoThis(
  narrative: NarrativeResponse | null,
  attribution: AttributionResponse | null,
  execution: ExecutionResponse | null
): string[] {
  const out: string[] = [];

  for (const h of narrative?.hypotheses ?? []) {
    out.push(plainPoint(h));
    if (out.length >= 3) break;
  }

  // Best / worst cohort in plain English if hypotheses are thin.
  if (out.length < 3 && attribution) {
    const rows = Object.values(attribution.cohorts).flat();
    const ranked = [...rows].sort(
      (a, b) => (b.avg_pnl ?? 0) - (a.avg_pnl ?? 0)
    );
    const best = ranked.find((r) => (r.avg_pnl ?? 0) > 0 && r.n >= 5);
    const worst = [...ranked]
      .reverse()
      .find((r) => (r.avg_pnl ?? 0) < 0 && r.n >= 5);
    if (best && out.length < 3) {
      out.push(
        `Favor setups like ${best.key} - about ${money(best.avg_pnl)}/trade so far (${best.wins}/${best.n} wins).`
      );
    }
    if (worst && out.length < 3) {
      out.push(
        `Be careful with ${worst.key} - averaging ${money(worst.avg_pnl)}/trade (${worst.wins}/${worst.n} wins).`
      );
    }
  }

  const stops = execution?.live_stop_policy ?? narrative?.live_stop_policy;
  if (stops && out.length < 4) {
    if (stops.enabled) {
      out.push(
        `Hard-stop earnings credit losers around ${pct(stops.stop_loss_frac)} of max risk (tighter near expiry) - don't let a 50% win rate bleed via fat left tails.`
      );
    } else {
      out.push(
        "Hard stops are off on earnings credits - that's how a ~50% win rate still loses money (small wins, fat losses)."
      );
    }
  }

  const live = execution?.live_exit_policy;
  if (live?.enabled && out.length < 4) {
    const tp = pct(live.effective_pct);
    if (live.learned?.applicable) {
      out.push(
        `On winners that are working, the book is taking profits around a ${tp} move in the stock - consider the same discipline in your own trades.`
      );
    } else {
      out.push(
        `Default take-profit is around a ${tp} move while more trades grade - a simple rule you can mirror.`
      );
    }
  }

  const base = execution?.market_baseline;
  if (base && out.length < 4) {
    if (base.significant && base.avg_excess_move_5d > 0) {
      out.push(
        "Signals are beating the broad tape after the print - the ideas themselves look useful, not just a bull market."
      );
    } else if (base.avg_excess_move_5d <= 0) {
      out.push(
        "After the print, picks aren't clearly beating the market - size smaller until that turns."
      );
    }
  }

  return out.slice(0, 4);
}

function buildChanged(progress: ProgressResponse | null): string[] {
  const week = latestWeek(progress);
  if (!week) return [];
  return (week.changes ?? []).map((c) =>
    plainPoint(c)
      .replace(
        /Predictions got closer to reality/gi,
        "Our odds calls got closer to what actually happened"
      )
      .replace(
        /Predictions drifted further from reality/gi,
        "Our odds calls drifted further from what actually happened"
      )
  );
}

export function LearningTakeaways({
  narrative,
  progress,
  attribution,
  execution,
}: {
  narrative: NarrativeResponse | null;
  progress: ProgressResponse | null;
  attribution: AttributionResponse | null;
  execution: ExecutionResponse | null;
}) {
  const doThis = buildDoThis(narrative, attribution, execution);
  const changed = buildChanged(progress);
  const week = latestWeek(progress);
  const overall = attribution?.overall;

  if (!doThis.length && !changed.length && !overall) return null;

  return (
    <Card className="p-5 mb-6 border-[var(--color-accent)]/35">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <div
            className="text-[11px] font-semibold uppercase tracking-wide mb-1"
            style={{ color: ACCENT }}
          >
            Start here
          </div>
          <h2 className="text-xl font-semibold tracking-tight">
            What this means for your trades
          </h2>
          <p className="text-sm text-[var(--color-muted)] mt-1 max-w-2xl">
            Plain-English takeaways from the paper book - use them as a checklist
            when you size your own earnings trades.
          </p>
        </div>
        {overall?.n ? (
          <div className="text-right text-sm shrink-0">
            <div className="text-[var(--color-muted)] text-xs uppercase tracking-wide">
              Paper book so far
            </div>
            <div className="font-semibold tabular-nums">
              <span style={{ color: (overall.total_pnl ?? 0) >= 0 ? PROFIT : LOSS }}>
                {money(overall.total_pnl)}
              </span>
              <span className="text-[var(--color-muted)] font-normal">
                {" "}
                · {pct(overall.win_rate)} wins · {overall.n} closed
              </span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div>
          <div
            className="text-[11px] font-semibold uppercase tracking-wide mb-2"
            style={{ color: PROFIT }}
          >
            Do this
          </div>
          {doThis.length ? (
            <ul className="space-y-2">
              {doThis.map((line, i) => (
                <li
                  key={i}
                  className="text-sm leading-relaxed text-[#e8edf7] flex gap-2"
                >
                  <span style={{ color: PROFIT }} className="shrink-0">
                    →
                  </span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--color-muted)]">
              Not enough closed trades yet for concrete playbook advice.
            </p>
          )}
        </div>

        <div>
          <div
            className="text-[11px] font-semibold uppercase tracking-wide mb-2"
            style={{ color: WARN }}
          >
            What changed{week ? ` · ${week.label}` : ""}
          </div>
          {changed.length ? (
            <ul className="space-y-2">
              {changed.map((line, i) => (
                <li
                  key={i}
                  className="text-sm leading-relaxed text-[#c9d2e3] flex gap-2"
                >
                  <span className="text-[var(--color-muted)] shrink-0">·</span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--color-muted)]">
              No week-to-week change to call out yet.
            </p>
          )}
        </div>
      </div>

      {narrative?.headline ? (
        <p className="mt-4 pt-4 border-t border-[var(--color-edge)] text-sm text-[var(--color-muted)]">
          <span className="text-white font-medium">In one line: </span>
          {plainPoint(narrative.headline)}
        </p>
      ) : null}
    </Card>
  );
}
