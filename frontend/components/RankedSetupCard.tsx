"use client";

import Link from "next/link";
import type { RankedSetup } from "@/lib/api";
import { BlurValue } from "@/components/BlurValue";
import { SampleTierBadge } from "@/components/SampleTierBadge";
import { Card, ThemePill } from "@/components/ui";
import { fmtDate, moveClass, pct, signedPct } from "@/lib/format";

export function RankedSetupCard({
  setup,
  blur = false,
  variant = "default",
}: {
  setup: RankedSetup;
  blur?: boolean;
  /** hero = today's focus; compact = secondary board rows */
  variant?: "hero" | "default" | "compact";
}) {
  const kindLabel = setup.kind === "wave" ? "Wave" : "Drift";
  const kindColor = setup.kind === "wave" ? "#5b8def" : "#28c08a";
  const boardHref = setup.board_href || (setup.kind === "wave" ? "/waves" : "/drift");

  if (variant === "compact") {
    return (
      <div className="flex items-start gap-3 py-3 border-t border-[var(--color-edge)] first:border-t-0 first:pt-0">
        <span className="text-xs text-[var(--color-muted)] font-mono w-5 shrink-0 pt-0.5">
          #{setup.rank}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={setup.href || `/company/${setup.ticker}`}
              className="font-semibold hover:text-[var(--color-accent)]"
            >
              {setup.ticker}
            </Link>
            <span
              className="text-[10px] font-semibold uppercase tracking-wide"
              style={{ color: kindColor }}
            >
              {kindLabel}
            </span>
            <SampleTierBadge tier={setup.sample_tier} />
          </div>
          <p className="text-sm text-[var(--color-muted)] mt-0.5">{setup.headline}</p>
          {setup.action ? (
            <BlurValue active={blur}>
              <p className="text-sm mt-1">{setup.action}</p>
            </BlurValue>
          ) : null}
        </div>
        <div className="text-right shrink-0 text-sm">
          <BlurValue active={blur}>
            <span className={`font-semibold tabular-nums ${moveClass(setup.edge_pct)}`}>
              {signedPct(setup.edge_pct, 1)}
            </span>
          </BlurValue>
        </div>
      </div>
    );
  }

  const isHero = variant === "hero";

  return (
    <Card className={`p-4 ${isHero ? "border-[var(--color-accent)]/40" : ""}`}>
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            {isHero ? (
              <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--color-accent)]">
                Today&apos;s focus
              </span>
            ) : (
              <span className="text-xs text-[var(--color-muted)] font-mono">
                #{setup.rank}
              </span>
            )}
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
            <SampleTierBadge tier={setup.sample_tier} />
          </div>
          <Link
            href={setup.href || `/company/${setup.ticker}`}
            className={`font-semibold hover:text-[var(--color-accent)] ${
              isHero ? "text-xl" : "text-base"
            }`}
          >
            {setup.ticker}
            {setup.name ? (
              <span className="text-[var(--color-muted)] font-normal text-sm ml-2">
                {setup.name}
              </span>
            ) : null}
          </Link>
          <p className="text-sm mt-1 text-[var(--color-muted)]">{setup.headline}</p>
        </div>
        <div className="text-right shrink-0 text-sm">
          <div className="text-[var(--color-muted)] text-xs">Hist. edge</div>
          <BlurValue active={blur}>
            <span
              className={`font-semibold tabular-nums ${
                isHero ? "text-lg" : ""
              } ${moveClass(setup.edge_pct)}`}
            >
              {signedPct(setup.edge_pct, 1)}
            </span>
          </BlurValue>
          {setup.report_date ? (
            <div className="text-xs text-[var(--color-muted)] mt-1">
              {fmtDate(setup.report_date)}
            </div>
          ) : null}
        </div>
      </div>

      {setup.action ? (
        <BlurValue active={blur}>
          <p className={`mb-3 ${isHero ? "text-base" : "text-sm"}`}>{setup.action}</p>
        </BlurValue>
      ) : null}

      {(setup.themes?.length ?? 0) > 0 ? (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {setup.themes.slice(0, 3).map((t) => (
            <ThemePill key={t.key} theme={t} />
          ))}
        </div>
      ) : null}

      <ul className="space-y-1 mb-3">
        {(setup.why ?? []).slice(0, isHero ? 3 : 2).map((w, i) => (
          <li key={i} className="text-sm text-[var(--color-muted)] flex gap-2">
            <span className="text-[var(--color-accent)] shrink-0">•</span>
            <span>{w}</span>
          </li>
        ))}
      </ul>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-0.5">
            Watch
          </div>
          <BlurValue active={blur}>
            <p className="text-[var(--color-muted)]">{setup.watch}</p>
          </BlurValue>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-0.5">
            Drop if
          </div>
          <BlurValue active={blur}>
            <p className="text-[var(--color-muted)]">{setup.invalidation}</p>
          </BlurValue>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-[var(--color-edge)] flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-muted)]">
        {setup.win_rate != null ? (
          <span>
            Win{" "}
            <BlurValue active={blur}>
              <span className="text-white">{pct(setup.win_rate, 0)}</span>
            </BlurValue>
            {setup.win_rate_ci_low != null ? (
              <span> · floor {pct(setup.win_rate_ci_low, 0)}</span>
            ) : null}
          </span>
        ) : null}
        {setup.sample_size != null ? <span>n={setup.sample_size}</span> : null}
        <Link href={boardHref} className="text-[var(--color-accent)] hover:underline ml-auto">
          {kindLabel} board →
        </Link>
      </div>
    </Card>
  );
}
