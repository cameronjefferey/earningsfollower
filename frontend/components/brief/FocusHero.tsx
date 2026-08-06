"use client";

import Link from "next/link";
import type { BoardQuality, RankedSetup } from "@/lib/api";
import { BlurValue, BlurZone } from "@/components/BlurValue";
import { SampleTierBadge } from "@/components/SampleTierBadge";
import { ThemePill } from "@/components/ui";
import { fmtDate, pct, signedPct } from "@/lib/format";

function convColor(label?: string): string {
  if (label === "High") return "var(--color-up)";
  if (label === "Medium") return "var(--color-accent)";
  if (label === "Speculative") return "#e0a33e";
  return "var(--color-muted)";
}

function ConvictionRing({
  value,
  label,
}: {
  value?: number;
  label?: string;
}) {
  const v = Math.max(0, Math.min(100, value ?? 0));
  const color = convColor(label);
  return (
    <div className="flex flex-col items-center shrink-0">
      <div
        className="relative h-20 w-20 rounded-full"
        style={{
          background: `conic-gradient(${color} ${v * 3.6}deg, var(--color-edge) 0deg)`,
        }}
        role="img"
        aria-label={`Conviction ${v} of 100 (${label ?? "n/a"})`}
      >
        <div className="absolute inset-[7px] rounded-full bg-[var(--color-panel)] flex flex-col items-center justify-center">
          <span className="text-xl font-semibold tabular leading-none">{v}</span>
          <span className="text-[9px] uppercase tracking-wide text-[var(--color-muted)] mt-0.5">
            / 100
          </span>
        </div>
      </div>
      <span
        className="mt-2 text-[11px] font-semibold uppercase tracking-wide"
        style={{ color }}
      >
        {label ?? "—"}
      </span>
      <span className="text-[10px] text-[var(--color-muted)] uppercase tracking-wide">
        Conviction
      </span>
    </div>
  );
}

/** Edge magnitude + hit rate, made visual. */
function EdgeViz({ setup }: { setup: RankedSetup }) {
  const edge = setup.edge_pct ?? 0;
  const edgeWidth = Math.min(Math.abs(edge) / 0.15, 1) * 100;
  const win = setup.win_rate ?? null;
  const floor = setup.win_rate_ci_low ?? null;
  const edgeColor =
    edge >= 0 ? "var(--color-up)" : "var(--color-down)";

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div>
        <div className="flex items-baseline justify-between mb-1">
          <span className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
            Historical target
          </span>
          <span
            className="text-sm font-semibold tabular"
            style={{ color: edgeColor }}
          >
            {signedPct(edge, 1)}
          </span>
        </div>
        <div className="h-2 rounded-full bg-[var(--color-panel-2)] overflow-hidden">
          <div
            className="h-full rounded-full"
            style={{ width: `${edgeWidth}%`, backgroundColor: edgeColor }}
          />
        </div>
        <div className="text-[10px] text-[var(--color-muted)] mt-1">
          Scaled to a 15% move
        </div>
      </div>

      <div>
        <div className="flex items-baseline justify-between mb-1">
          <span className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
            Win rate
          </span>
          <span className="text-sm font-semibold tabular text-white">
            {win != null ? pct(win, 0) : "—"}
          </span>
        </div>
        <div className="relative h-2 rounded-full bg-[var(--color-panel-2)] overflow-hidden">
          <div
            className="h-full rounded-full bg-[var(--color-accent)]"
            style={{ width: `${(win ?? 0) * 100}%` }}
          />
          {floor != null ? (
            <div
              className="absolute top-[-2px] bottom-[-2px] w-0.5 bg-white/70"
              style={{ left: `${floor * 100}%` }}
              title={`Wilson floor ${pct(floor, 0)}`}
            />
          ) : null}
        </div>
        <div className="text-[10px] text-[var(--color-muted)] mt-1">
          {floor != null
            ? `Wilson floor ${pct(floor, 0)} · n=${setup.sample_size ?? "—"}`
            : `n=${setup.sample_size ?? "—"}`}
        </div>
      </div>
    </div>
  );
}

function PlanCell({
  label,
  value,
  locked,
}: {
  label: string;
  value?: string;
  locked?: boolean;
}) {
  return (
    <div className="rounded-lg bg-[var(--color-panel-2)]/60 border border-[var(--color-edge)]/60 p-3">
      <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)] mb-1">
        {label}
      </div>
      {locked ? (
        <BlurValue active>
          <p className="text-sm text-white">{value || "Pro detail"}</p>
        </BlurValue>
      ) : (
        <p className="text-sm text-white leading-snug">{value || "—"}</p>
      )}
    </div>
  );
}

function WavePeers({ setup }: { setup: RankedSetup }) {
  const peers = (setup.cluster_peers ?? []).slice(0, 6);
  if (!peers.length) return null;
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <h3 className="text-sm font-semibold text-white">Rest of this wave</h3>
        <span className="text-xs text-[var(--color-muted)]">
          same driver ({setup.trigger ?? "peer"}) · correlated, not independent
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {peers.map((p) => (
          <Link
            key={p.ticker}
            href={p.href || `/company/${p.ticker}`}
            className="rounded-lg border border-[var(--color-edge)]/70 bg-[var(--color-panel)] px-3 py-2 hover:border-[var(--color-accent)]/50 transition-colors"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-semibold text-sm">{p.ticker}</span>
              <span className="text-xs tabular text-[var(--color-muted)]">
                {signedPct(p.edge_pct, 1)}
              </span>
            </div>
            <div className="text-[10px] text-[var(--color-muted)] mt-0.5">
              {p.win_rate != null ? `win ${pct(p.win_rate, 0)}` : ""}
              {p.sample_size != null ? ` · n=${p.sample_size}` : ""}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

export function FocusHero({
  setup,
  preview = false,
}: {
  setup: RankedSetup;
  preview?: boolean;
}) {
  const kindLabel = setup.kind === "wave" ? "Peer wave" : "Post-earnings drift";
  const kindColor = setup.kind === "wave" ? "#5b8def" : "#28c08a";
  const dirLong = setup.direction !== "bearish";
  const plan = setup.plan;

  return (
    <div className="rounded-xl border border-[var(--color-accent)]/30 bg-gradient-to-b from-[var(--color-panel)] to-[var(--color-ink)] p-5 sm:p-6">
      <div className="flex items-start justify-between gap-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span
              className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide border"
              style={{
                color: kindColor,
                borderColor: `${kindColor}55`,
                backgroundColor: `${kindColor}1a`,
              }}
            >
              {kindLabel}
            </span>
            <span
              className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                dirLong
                  ? "bg-[var(--color-up)]/15 text-[var(--color-up)]"
                  : "bg-[var(--color-down)]/15 text-[var(--color-down)]"
              }`}
            >
              {dirLong ? "Long bias" : "Short bias"}
            </span>
            <SampleTierBadge tier={setup.sample_tier} />
          </div>

          <BlurZone active={preview} label="Pro — today's lean">
            <div className="flex items-baseline gap-2 flex-wrap">
              {preview ? (
                <span className="text-3xl font-semibold tracking-tight">
                  {setup.ticker}
                </span>
              ) : (
                <Link
                  href={setup.href || `/company/${setup.ticker}`}
                  className="text-3xl font-semibold tracking-tight hover:text-[var(--color-accent)]"
                >
                  {setup.ticker}
                </Link>
              )}
              {setup.name ? (
                <span className="text-sm text-[var(--color-muted)]">{setup.name}</span>
              ) : null}
            </div>

            {plan?.thesis ? (
              <p className="mt-3 text-base leading-relaxed max-w-2xl">{plan.thesis}</p>
            ) : (
              <p className="mt-3 text-base text-[var(--color-muted)]">{setup.headline}</p>
            )}

            {plan?.trigger_status ? (
              <div className="mt-3 inline-flex items-center gap-2 text-sm text-[var(--color-muted)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-up)] animate-pulse" />
                {plan.trigger_status}
              </div>
            ) : null}
          </BlurZone>
        </div>

        <BlurZone active={preview} label="Pro">
          <ConvictionRing value={setup.conviction} label={setup.conviction_label} />
        </BlurZone>
      </div>

      <BlurZone active={preview} label="Pro stats" className="mt-5">
        <EdgeViz setup={setup} />
      </BlurZone>

      <div className="mt-5 grid grid-cols-2 lg:grid-cols-4 gap-3">
        <PlanCell label="Target" value={plan?.target} locked={preview} />
        <PlanCell label="Window" value={plan?.window} locked={preview} />
        <PlanCell label="Invalidate" value={plan?.invalidation} locked={preview} />
        <PlanCell label="Sizing" value={plan?.sizing} locked={preview} />
      </div>

      {(setup.themes?.length ?? 0) > 0 ? (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {setup.themes.slice(0, 4).map((t) => (
            <ThemePill key={t.key} theme={t} />
          ))}
        </div>
      ) : null}

      <div className="mt-4 pt-4 border-t border-[var(--color-edge)] flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-muted)]">
        {setup.report_date && !preview ? (
          <span>Reports {fmtDate(setup.report_date)}</span>
        ) : null}
        {preview ? (
          <span className="text-[var(--color-muted)] ml-auto">
            Unlock Pro for today&apos;s ranked lean
          </span>
        ) : (
          <Link
            href={setup.kind === "wave" ? "/boards?tab=waves" : "/boards?tab=drift"}
            className="text-[var(--color-accent)] hover:underline ml-auto"
          >
            {setup.kind === "wave" ? "Wave" : "Drift"} board →
          </Link>
        )}
      </div>

      {!preview ? (
        <div className="mt-5">
          <WavePeers setup={setup} />
        </div>
      ) : null}
    </div>
  );
}

export function BoardQualityBar({ q }: { q: BoardQuality }) {
  const narrow = q.distinct_drivers <= 1;
  const items: { label: string; value: string; tone?: string }[] = [
    {
      label: "Distinct drivers",
      value: String(q.distinct_drivers),
      tone: narrow ? "warn" : undefined,
    },
    {
      label: "Sample",
      value: `${q.solid} solid · ${q.ok} ok · ${q.thin} thin`,
    },
    {
      label: "Median win floor",
      value: q.median_win_floor != null ? pct(q.median_win_floor, 0) : "—",
    },
    {
      label: "Best edge",
      value: q.best_edge_pct != null ? signedPct(q.best_edge_pct, 1) : "—",
    },
  ];

  return (
    <div className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)] p-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <h2 className="text-sm font-semibold text-white">Today&apos;s board</h2>
        <span
          className={`text-xs ${
            narrow ? "text-[#e0a33e]" : "text-[var(--color-muted)]"
          }`}
        >
          {narrow
            ? "Narrow day — one dominant driver. Don't mistake peers for diversification."
            : `${q.distinct_drivers} independent drivers today.`}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {items.map((it) => (
          <div key={it.label}>
            <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
              {it.label}
            </div>
            <div
              className={`text-sm font-semibold tabular mt-0.5 ${
                it.tone === "warn" ? "text-[#e0a33e]" : "text-white"
              }`}
            >
              {it.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
