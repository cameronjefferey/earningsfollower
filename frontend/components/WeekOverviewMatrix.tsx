"use client";

import Link from "next/link";
import { Fragment, useMemo } from "react";
import { EarningsCard } from "@/lib/api";
import { moveClass, pct, signedPct } from "@/lib/format";

const TOP_PER_SESSION = 10;

type DayCol = {
  date: string;
  label: string; // "Mon 11"
  bmo: EarningsCard[];
  amc: EarningsCard[];
};

function mondayOfWeekContaining(d: Date): Date {
  const out = new Date(d);
  out.setHours(0, 0, 0, 0);
  const offset = (out.getDay() + 6) % 7; // Mon=0
  out.setDate(out.getDate() - offset);
  return out;
}

function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function weekMonday(windowKey: "week" | "last_week"): Date {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const mon = mondayOfWeekContaining(today);
  if (windowKey === "last_week") mon.setDate(mon.getDate() - 7);
  return mon;
}

function dayLabel(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00`);
  const wd = d.toLocaleDateString(undefined, { weekday: "short" });
  return `${wd} ${d.getDate()}`;
}

/** Magnitude used for ranking: printed move when reported, else implied. */
function rankMove(card: EarningsCard): number | null {
  if (card.reported && card.actual_move_pct != null) {
    return Math.abs(card.actual_move_pct);
  }
  return card.implied_move_pct ?? card.avg_abs_move_pct;
}

/** Rank for the matrix: biggest move first, then market cap. */
function rankCards(cards: EarningsCard[]): EarningsCard[] {
  return [...cards].sort((a, b) => {
    const ai = rankMove(a);
    const bi = rankMove(b);
    if (ai == null && bi == null) {
      return (b.market_cap ?? 0) - (a.market_cap ?? 0);
    }
    if (ai == null) return 1;
    if (bi == null) return -1;
    if (bi !== ai) return bi - ai;
    return (b.market_cap ?? 0) - (a.market_cap ?? 0);
  });
}

function buildDays(
  cards: EarningsCard[],
  windowKey: "week" | "last_week"
): DayCol[] {
  const mon = weekMonday(windowKey);
  const byDate = new Map<string, EarningsCard[]>();
  for (const c of cards) {
    const key = c.date.slice(0, 10);
    const list = byDate.get(key);
    if (list) list.push(c);
    else byDate.set(key, [c]);
  }

  const days: DayCol[] = [];
  for (let i = 0; i < 5; i++) {
    const d = new Date(mon);
    d.setDate(mon.getDate() + i);
    const date = iso(d);
    const dayCards = byDate.get(date) ?? [];
    days.push({
      date,
      label: dayLabel(date),
      bmo: rankCards(dayCards.filter((c) => c.timing === "bmo")).slice(
        0,
        TOP_PER_SESSION
      ),
      amc: rankCards(dayCards.filter((c) => c.timing === "amc")).slice(
        0,
        TOP_PER_SESSION
      ),
    });
  }
  return days;
}

/**
 * Compact Mon–Fri matrix: each day has Before / After columns with the top
 * names by implied move. Sits above the day accordion for a fast week scan.
 */
export function WeekOverviewMatrix({
  cards,
  windowKey,
}: {
  cards: EarningsCard[];
  windowKey: "week" | "last_week";
}) {
  const days = useMemo(() => buildDays(cards, windowKey), [cards, windowKey]);
  const today = iso(new Date());
  const maxRows = Math.max(
    1,
    ...days.map((d) => Math.max(d.bmo.length, d.amc.length))
  );

  return (
    <div className="mb-4 overflow-x-auto rounded-xl border border-[var(--color-edge)] bg-[var(--color-panel)]/40">
      <table className="w-full min-w-[52rem] border-collapse text-sm">
        <thead>
          <tr className="border-b border-[var(--color-edge)]">
            {days.map((d) => (
              <th
                key={d.date}
                colSpan={2}
                className={`px-2 pt-2.5 pb-1 text-center text-xs font-semibold tracking-wide ${
                  d.date === today
                    ? "text-[var(--color-accent)]"
                    : "text-white"
                }`}
              >
                {d.label}
                {d.date === today ? (
                  <span className="ml-1 text-[10px] uppercase">Today</span>
                ) : null}
              </th>
            ))}
          </tr>
          <tr className="border-b border-[var(--color-edge)] text-[10px] uppercase tracking-wide text-[var(--color-muted)]">
            {days.map((d, i) => (
              <Fragment key={d.date}>
                <th className="px-1.5 py-1 font-medium text-left w-[10%]">
                  Before
                </th>
                <th
                  className={`px-1.5 py-1 font-medium text-left w-[10%] ${
                    i < days.length - 1
                      ? "border-r border-[var(--color-edge)]/50"
                      : ""
                  }`}
                >
                  After
                </th>
              </Fragment>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: maxRows }, (_, row) => (
            <tr
              key={row}
              className="border-b border-[var(--color-edge)]/40 last:border-b-0"
            >
              {days.map((d, i) => (
                <Fragment key={d.date}>
                  <SessionCell card={d.bmo[row]} dayEdge={false} />
                  <SessionCell
                    card={d.amc[row]}
                    dayEdge={i < days.length - 1}
                  />
                </Fragment>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-3 py-2 text-[11px] text-[var(--color-muted)] border-t border-[var(--color-edge)]/50">
        Top {TOP_PER_SESSION} per session by move size · reported shows printed
        move · filters apply · expand a day below for the full list
      </p>
    </div>
  );
}

function SessionCell({
  card,
  dayEdge,
}: {
  card: EarningsCard | undefined;
  /** Right border after the day's After column. */
  dayEdge: boolean;
}) {
  return (
    <td
      className={`px-1.5 py-1 align-top ${
        dayEdge ? "border-r border-[var(--color-edge)]/50" : ""
      }`}
    >
      {card ? (
        <Link
          href={`/company/${card.ticker}`}
          className="block rounded px-1 py-0.5 hover:bg-[var(--color-panel-2)] transition-colors"
          title={card.name ?? card.ticker}
        >
          <span className="font-semibold text-white">{card.ticker}</span>
          {card.reported && card.actual_move_pct != null ? (
            <span
              className={`ml-1 text-[11px] tabular ${moveClass(card.actual_move_pct)}`}
            >
              {signedPct(card.actual_move_pct)}
            </span>
          ) : (
            <span className="ml-1 text-[11px] tabular text-[var(--color-muted)]">
              {card.implied_move_pct != null
                ? `±${pct(Math.abs(card.implied_move_pct))}`
                : card.avg_abs_move_pct != null
                  ? `±${pct(Math.abs(card.avg_abs_move_pct))}`
                  : ""}
            </span>
          )}
        </Link>
      ) : (
        <span className="block h-6" aria-hidden />
      )}
    </td>
  );
}
