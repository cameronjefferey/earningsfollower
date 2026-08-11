"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { EarningsCard } from "@/lib/api";
import { fmtDate, marketCap, moveClass, pct, signedPct, timingLabel } from "@/lib/format";
import { ThemePill } from "@/components/ui";

type DayGroup = {
  date: string;
  label: string;
  cards: EarningsCard[];
  bmo: EarningsCard[];
  amc: EarningsCard[];
  other: EarningsCard[];
};

function todayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function groupByDay(cards: EarningsCard[]): DayGroup[] {
  const byDate = new Map<string, EarningsCard[]>();
  for (const c of cards) {
    const key = c.date.slice(0, 10);
    const list = byDate.get(key);
    if (list) list.push(c);
    else byDate.set(key, [c]);
  }
  return [...byDate.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([date, dayCards]) => ({
      date,
      label: fmtDate(date),
      cards: dayCards,
      bmo: dayCards.filter((c) => c.timing === "bmo"),
      amc: dayCards.filter((c) => c.timing === "amc"),
      other: dayCards.filter((c) => c.timing !== "bmo" && c.timing !== "amc"),
    }));
}

/** Day-by-day accordion for This week / Last week. Filters already applied upstream. */
export function WeekDayCalendar({ cards }: { cards: EarningsCard[] }) {
  const days = useMemo(() => groupByDay(cards), [cards]);
  const today = todayIso();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [seededToday, setSeededToday] = useState(false);

  // Open today's day once when it appears in the filtered set (This week).
  useEffect(() => {
    if (seededToday) return;
    if (!days.some((d) => d.date === today)) return;
    setOpen((prev) => {
      if (prev.has(today)) return prev;
      const next = new Set(prev);
      next.add(today);
      return next;
    });
    setSeededToday(true);
  }, [days, today, seededToday]);

  if (days.length === 0) return null;

  const toggle = (date: string) => {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(date)) next.delete(date);
      else next.add(date);
      return next;
    });
  };

  return (
    <div className="space-y-2">
      {days.map((day) => {
        const isOpen = open.has(day.date);
        const isToday = day.date === today;
        return (
          <div
            key={day.date}
            className="rounded-xl border border-[var(--color-edge)] bg-[var(--color-panel)]/60 overflow-hidden"
          >
            <button
              type="button"
              onClick={() => toggle(day.date)}
              aria-expanded={isOpen}
              className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-[var(--color-panel-2)]/50 transition-colors"
            >
              <span
                className={`text-[var(--color-muted)] transition-transform ${
                  isOpen ? "rotate-90" : ""
                }`}
                aria-hidden
              >
                ▸
              </span>
              <span className="font-semibold text-white">
                {day.label}
                {isToday ? (
                  <span className="ml-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-accent)]">
                    Today
                  </span>
                ) : null}
              </span>
              <span className="ml-auto text-sm text-[var(--color-muted)] tabular">
                {day.cards.length} {day.cards.length === 1 ? "name" : "names"}
              </span>
            </button>

            {isOpen ? (
              <div className="border-t border-[var(--color-edge)] px-2 pb-2 pt-1">
                <TimingSection label="Before open" cards={day.bmo} />
                <TimingSection label="After close" cards={day.amc} />
                <TimingSection label="Timing TBD" cards={day.other} />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

/** Shared column template so headers and rows stay lined up. */
const ROW_GRID =
  "grid grid-cols-[4.5rem_minmax(0,1fr)_4.5rem_4.5rem_3.75rem] sm:grid-cols-[5rem_minmax(0,1fr)_5rem_5rem_4.25rem_6.5rem] gap-x-3 items-center";

function TimingSection({
  label,
  cards,
}: {
  label: string;
  cards: EarningsCard[];
}) {
  if (cards.length === 0) return null;
  return (
    <div className="mt-2">
      <div className="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">
        {label}
        <span className="ml-1.5 font-normal tabular">{cards.length}</span>
      </div>
      <div
        className={`${ROW_GRID} px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-muted)]`}
      >
        <span>Ticker</span>
        <span>Name</span>
        <span className="text-right">Move</span>
        <span className="text-right" title="Priced-in implied when reported; historical avg otherwise">
          Expected
        </span>
        <span className="text-right">Cap</span>
        <span className="hidden sm:block">Theme</span>
      </div>
      <ul className="divide-y divide-[var(--color-edge)]/60">
        {cards.map((c) => (
          <CompanyRow key={`${c.ticker}-${c.date}`} card={c} />
        ))}
      </ul>
    </div>
  );
}

function bandCell(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-";
  return `±${pct(Math.abs(value))}`;
}

function CompanyRow({ card }: { card: EarningsCard }) {
  const theme = card.themes[0];
  const when = timingLabel(card.timing);
  const reported = card.reported;
  const moveValue = reported
    ? card.actual_move_pct
    : card.implied_move_pct ?? card.avg_abs_move_pct;
  const pricedIn = reported
    ? card.priced_in_move_pct
    : card.avg_abs_move_pct;

  return (
    <li>
      <Link
        href={`/company/${card.ticker}`}
        className={`${ROW_GRID} px-2 py-2.5 rounded-lg hover:bg-[var(--color-panel-2)] transition-colors`}
      >
        <span className="font-semibold text-white truncate">{card.ticker}</span>
        <span className="min-w-0 truncate text-sm text-[var(--color-muted)]">
          {card.name ?? card.sector ?? when ?? ""}
        </span>
        <span
          className={`text-sm tabular text-right ${
            reported ? moveClass(card.actual_move_pct) : "text-white"
          }`}
        >
          {reported ? signedPct(moveValue) : bandCell(moveValue)}
        </span>
        <span className="text-sm tabular text-[var(--color-muted)] text-right">
          {bandCell(pricedIn)}
        </span>
        <span className="text-xs text-[var(--color-muted)] tabular text-right">
          {marketCap(card.market_cap)}
        </span>
        <span className="hidden sm:flex justify-end min-w-0">
          {theme ? <ThemePill theme={theme} /> : null}
        </span>
      </Link>
    </li>
  );
}
