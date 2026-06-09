import Link from "next/link";
import { EarningsCard } from "@/lib/api";
import { fmtDate, marketCap, moveClass, pct, signedPct, timingLabel } from "@/lib/format";
import { glossary } from "@/lib/glossary";
import { Card, ThemePill, VerdictPill } from "./ui";
import { InfoTip } from "./InfoTip";

export function EarningsCardItem({ card }: { card: EarningsCard }) {
  const headline = card.implied_move_pct ?? card.avg_abs_move_pct;
  const headlineLabel = card.implied_move_pct ? "Implied move" : "Avg move";

  return (
    <Link href={`/company/${card.ticker}`} className="group">
      <Card className="p-4 h-full transition-colors group-hover:border-[var(--color-accent)]/60">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold">{card.ticker}</span>
              {card.reported ? (
                <span className="text-[10px] uppercase tracking-wide rounded px-1.5 py-0.5 bg-[var(--color-panel-2)] text-[var(--color-muted)]">
                  Reported
                </span>
              ) : null}
            </div>
            <div className="text-xs text-[var(--color-muted)] truncate">
              {card.name ?? card.sector ?? "—"}
            </div>
          </div>
          <div className="text-right shrink-0">
            <div className="text-sm font-medium">{fmtDate(card.date)}</div>
            <div className="text-xs text-[var(--color-muted)]">
              {timingLabel(card.timing)}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5 mt-3">
          {card.themes.map((t) => (
            <ThemePill key={t.key} theme={t} />
          ))}
        </div>

        <div className="grid grid-cols-3 gap-2 mt-4">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
              {headlineLabel}
              <InfoTip
                text={card.implied_move_pct ? glossary.implied_move : glossary.avg_move}
              />
            </div>
            <div className="text-base font-semibold">{pct(headline)}</div>
            <div className="mt-0.5">
              <VerdictPill verdict={card.implied_verdict} />
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
              {card.reported ? "Last move" : "Hist. up rate"}
              <InfoTip text={card.reported ? glossary.last_move : glossary.up_rate} />
            </div>
            <div
              className={`text-base font-semibold ${
                card.reported ? moveClass(card.last_move_pct) : ""
              }`}
            >
              {card.reported ? signedPct(card.last_move_pct) : pct(card.up_rate, 0)}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
              Beat streak
              <InfoTip text={glossary.beat_streak} />
            </div>
            <div className="text-base font-semibold">
              {card.beat_streak > 0 ? `${card.beat_streak}Q` : "—"}
            </div>
          </div>
        </div>

        <div className="mt-3 pt-3 border-t border-[var(--color-edge)] flex items-center justify-between text-xs text-[var(--color-muted)]">
          <span>{marketCap(card.market_cap)}</span>
          <span className="group-hover:text-[var(--color-accent)] transition-colors">
            View detail →
          </span>
        </div>
      </Card>
    </Link>
  );
}
