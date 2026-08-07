"use client";

import { NarrativeResponse } from "@/lib/api";
import { Card } from "./ui";
import { InfoTip } from "./InfoTip";

const ACCENT = "#5b8cff";
const PROFIT = "#28c08a";
const WARN = "#f0a85b";

const SECTION_TITLE: Record<string, string> = {
  "What's working": "What's working",
  "What's not": "What's hurting",
  "What's hurting": "What's hurting",
  "Feature signal": "Clues at entry",
  "Clues at entry": "Clues at entry",
  Calibration: "Are the odds honest?",
  "Are the odds honest?": "Are the odds honest?",
  "Gate check (opened vs skipped)": "Are we passing on good trades?",
  "Are we passing on good trades?": "Are we passing on good trades?",
  "Risk exits live now": "Risk exits live now",
  "Lean into": "What's working",
  "Avoid or size down": "What's hurting",
};

function SourceBadge({ source }: { source: NarrativeResponse["source"] }) {
  const meta: Record<string, { label: string; color: string }> = {
    llm: { label: "Written summary", color: ACCENT },
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
        Odds adjustment
      </span>
      <InfoTip text="When on, each strategy gently nudges its win-odds using how that strategy has actually done — never a huge swing, just a reality check before new trades open." />
      <span
        className="ml-2 font-semibold"
        style={{ color: c.enabled ? PROFIT : "#8a97b1" }}
      >
        {c.enabled ? "on" : "off"}
      </span>
      {c.enabled && active.length ? (
        <span className="ml-2 text-[var(--color-muted)]">
          {active
            .map((s) => {
              const lean = s.multiplier > 1 ? "more willing" : "more cautious";
              return `${s.strategy} (${lean}, ${s.n} trades)`;
            })
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
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-sm">This week&apos;s read</h3>
            <SourceBadge source={report.source} />
            <InfoTip text="A short post-mortem from the closed-trade numbers. It only explains stats that already exist — it doesn't invent results." />
          </div>
          <p className="mt-1 text-sm text-white">{report.headline}</p>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
        {report.sections.map((s) => (
          <div key={s.title}>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted)] mb-1">
              {SECTION_TITLE[s.title] ?? s.title}
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
            Try this in your own book
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
