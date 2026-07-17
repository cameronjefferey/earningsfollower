"use client";

import { NarrativeResponse } from "@/lib/api";
import { Card } from "./ui";
import { InfoTip } from "./InfoTip";

const ACCENT = "#5b8cff";
const PROFIT = "#28c08a";
const WARN = "#f0a85b";

function SourceBadge({ source }: { source: NarrativeResponse["source"] }) {
  const meta: Record<string, { label: string; color: string }> = {
    llm: { label: "AI summary", color: ACCENT },
    heuristic: { label: "Auto summary", color: "#8a97b1" },
    empty: { label: "—", color: "#8a97b1" },
  };
  const m = meta[source] ?? meta.heuristic;
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold border whitespace-nowrap"
      style={{ color: m.color, borderColor: `${m.color}55`, backgroundColor: `${m.color}1a` }}
    >
      {m.label}
    </span>
  );
}

function CalibrationStatus({ report }: { report: NarrativeResponse }) {
  const c = report.calibration;
  if (!c) return null;
  const active = c.strategies.filter((s) => s.applicable);
  return (
    <div className="mt-3 rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2 text-[11px]">
      <span className="uppercase tracking-wide text-[var(--color-muted)]">
        Calibration feedback
      </span>
      <InfoTip text="When enabled, each strategy's model win-probability is recalibrated by its realized track record before the entry EV gate sees it — bounded so it can only nudge, never swing, the decision. Off by default." />
      <span
        className="ml-2 font-semibold"
        style={{ color: c.enabled ? PROFIT : "#8a97b1" }}
      >
        {c.enabled ? "on" : "off"}
      </span>
      {c.enabled && active.length ? (
        <span className="ml-2 text-[var(--color-muted)]">
          {active
            .map(
              (s) =>
                `${s.strategy} ×${s.multiplier.toFixed(2)} (n=${s.n})`
            )
            .join(" · ")}
        </span>
      ) : null}
    </div>
  );
}

export function Narrative({ report }: { report: NarrativeResponse | null }) {
  if (!report || report.source === "empty") return null;

  return (
    <Card className="p-4 mb-4 border-[#5b8cff]/30">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-sm">Read of the tape</h3>
            <SourceBadge source={report.source} />
            <InfoTip text="A plain-English post-mortem generated from the attribution numbers. It only narrates the stats — it never invents figures — and respects sample sizes and confidence intervals." />
          </div>
          <p className="mt-1 text-sm text-white">{report.headline}</p>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
        {report.sections.map((s) => (
          <div key={s.title}>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted)] mb-1">
              {s.title}
            </div>
            <ul className="space-y-1">
              {s.points.map((p, i) => (
                <li key={i} className="text-xs leading-relaxed text-[#c9d2e3] flex gap-1.5">
                  <span className="text-[var(--color-muted)]">·</span>
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {report.hypotheses.length ? (
        <div className="mt-3">
          <div
            className="text-[11px] font-semibold uppercase tracking-wide mb-1"
            style={{ color: WARN }}
          >
            Hypotheses to test
          </div>
          <ul className="space-y-1">
            {report.hypotheses.map((h, i) => (
              <li key={i} className="text-xs leading-relaxed text-[#c9d2e3] flex gap-1.5">
                <span style={{ color: WARN }}>→</span>
                <span>{h}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <CalibrationStatus report={report} />

      {report.caveats.length ? (
        <p className="mt-3 text-[10px] leading-relaxed text-[var(--color-muted)]">
          {report.caveats.join(" ")}
        </p>
      ) : null}
    </Card>
  );
}
