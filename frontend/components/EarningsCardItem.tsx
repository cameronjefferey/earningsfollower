import Link from "next/link";
import { ConvictionTier, EarningsCard } from "@/lib/api";
import { fmtDate, marketCap, moveClass, pct, signedPct, timingLabel } from "@/lib/format";
import { Card, ThemePill, VerdictPill } from "./ui";

const CONVICTION_STYLE: Record<
  ConvictionTier,
  { label: string; className: string }
> = {
  high: {
    label: "High",
    className: "bg-[var(--color-up)]/15 text-[var(--color-up)]",
  },
  medium: {
    label: "Med",
    className: "bg-[var(--color-accent)]/15 text-[var(--color-accent)]",
  },
  low: {
    label: "Low",
    className: "bg-[var(--color-panel-2)] text-[var(--color-muted)]",
  },
};

function vsImpliedLabel(ratio: number | null | undefined): string | null {
  if (ratio == null || Number.isNaN(ratio)) return null;
  if (ratio >= 1.15) return `${ratio.toFixed(1)}× priced-in`;
  if (ratio <= 0.85) return `${ratio.toFixed(1)}× priced-in`;
  return "Inline with priced-in";
}

export function EarningsCardItem({ card }: { card: EarningsCard }) {
  const theme = card.themes[0];
  const conviction = card.conviction ? CONVICTION_STYLE[card.conviction] : null;
  const when = timingLabel(card.timing);
  const reported = card.reported;
  const actual = card.actual_move_pct;
  const pricedIn = card.priced_in_move_pct;
  const vsLabel = vsImpliedLabel(card.move_vs_implied);

  const primary = reported
    ? actual
    : card.implied_move_pct ?? card.avg_abs_move_pct;
  const primaryLabel = reported
    ? "Printed"
    : card.implied_move_pct
      ? "Implied"
      : "Avg move";

  return (
    <Link href={`/company/${card.ticker}`} className="group block h-full">
      <Card className="p-5 h-full transition-colors group-hover:border-[var(--color-accent)]/50 border-[var(--color-edge)]/80">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xl font-semibold tracking-tight">{card.ticker}</span>
              {reported ? (
                <span className="text-[10px] uppercase tracking-wide rounded px-1.5 py-0.5 bg-[var(--color-panel-2)] text-[var(--color-muted)]">
                  Reported
                </span>
              ) : null}
              {!reported && conviction ? (
                <span
                  className={`text-[10px] uppercase tracking-wide rounded px-1.5 py-0.5 font-medium ${conviction.className}`}
                >
                  {conviction.label}
                </span>
              ) : null}
            </div>
            <div className="text-sm text-[var(--color-muted)] truncate mt-0.5">
              {card.name ?? card.sector ?? "-"}
            </div>
          </div>
          <div className="text-right shrink-0">
            <div className="text-sm font-medium tabular">{fmtDate(card.date)}</div>
            {when ? (
              <div className="text-xs text-[var(--color-muted)] mt-0.5">{when}</div>
            ) : null}
          </div>
        </div>

        <div className="mt-5 flex items-end justify-between gap-3">
          <div>
            <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-1">
              {primaryLabel}
            </div>
            <div
              className={`text-2xl font-semibold tabular leading-none ${
                reported ? moveClass(actual) : ""
              }`}
            >
              {reported ? signedPct(actual) : pct(primary)}
            </div>
            <div className="mt-1.5">
              {reported ? (
                vsLabel ? (
                  <span className="text-[11px] text-[var(--color-muted)]">{vsLabel}</span>
                ) : actual == null ? (
                  <span className="text-[11px] text-[var(--color-muted)]">
                    Awaiting session settle
                  </span>
                ) : null
              ) : (
                <VerdictPill verdict={card.implied_verdict} />
              )}
            </div>
          </div>
          <div className="text-right space-y-1">
            {reported ? (
              <>
                <div className="text-xs text-[var(--color-muted)]">
                  Priced in{" "}
                  <span className="font-medium text-white tabular">
                    {pricedIn != null ? `±${pct(Math.abs(pricedIn))}` : "—"}
                  </span>
                </div>
                <div className="text-xs text-[var(--color-muted)]">
                  Beat streak{" "}
                  <span className="font-medium text-white tabular">
                    {card.beat_streak > 0 ? `${card.beat_streak}Q` : "-"}
                  </span>
                </div>
              </>
            ) : (
              <>
                <div className="text-xs text-[var(--color-muted)]">
                  Up rate{" "}
                  <span className="font-medium tabular text-white">
                    {pct(card.up_rate, 0)}
                  </span>
                </div>
                <div className="text-xs text-[var(--color-muted)]">
                  Beat streak{" "}
                  <span className="font-medium text-white tabular">
                    {card.beat_streak > 0 ? `${card.beat_streak}Q` : "-"}
                  </span>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-[var(--color-edge)]/70 flex items-center justify-between gap-2 text-xs text-[var(--color-muted)]">
          <span className="tabular">{marketCap(card.market_cap)}</span>
          {theme ? <ThemePill theme={theme} /> : <span />}
        </div>
      </Card>
    </Link>
  );
}

export function EarningsCardSkeleton() {
  return (
    <Card className="p-5 h-full border-[var(--color-edge)]/60">
      <div className="flex justify-between gap-3">
        <div className="space-y-2 flex-1">
          <div className="skeleton h-6 w-20" />
          <div className="skeleton h-4 w-36" />
        </div>
        <div className="space-y-2 items-end flex flex-col">
          <div className="skeleton h-4 w-16" />
          <div className="skeleton h-3 w-12" />
        </div>
      </div>
      <div className="mt-5 flex justify-between">
        <div className="space-y-2">
          <div className="skeleton h-3 w-14" />
          <div className="skeleton h-8 w-20" />
        </div>
        <div className="space-y-2 items-end flex flex-col">
          <div className="skeleton h-3 w-24" />
          <div className="skeleton h-3 w-20" />
        </div>
      </div>
      <div className="mt-4 pt-3 border-t border-[var(--color-edge)]/50 flex justify-between">
        <div className="skeleton h-3 w-16" />
        <div className="skeleton h-5 w-16 rounded-full" />
      </div>
    </Card>
  );
}
