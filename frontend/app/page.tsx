"use client";

import { useEffect, useMemo, useState } from "react";
import { api, EarningsCard, Theme } from "@/lib/api";
import { EarningsCardItem } from "@/components/EarningsCardItem";
import { EmptyState, Spinner } from "@/components/ui";

const WINDOWS = [
  { key: "today", label: "Today" },
  { key: "week", label: "This week" },
  { key: "last_week", label: "Last week" },
  { key: "upcoming", label: "Upcoming" },
];

// Sort options. Each defines how to order cards within a group (or the flat
// list). "date" keeps the soonest reports first; the others rank high → low.
type SortKey = "date" | "implied_move" | "market_cap";
const SORTS: { key: SortKey; label: string }[] = [
  { key: "date", label: "Date" },
  { key: "implied_move", label: "Implied move" },
  { key: "market_cap", label: "Market cap" },
];

// Market-cap filter buckets, largest first. `min` is inclusive, `max` exclusive.
const CAP_BUCKETS: { key: string; label: string; min: number; max: number }[] = [
  { key: "mega", label: "Mega ($200B+)", min: 200e9, max: Infinity },
  { key: "large", label: "Large ($10–200B)", min: 10e9, max: 200e9 },
  { key: "mid", label: "Mid ($2–10B)", min: 2e9, max: 10e9 },
  { key: "small", label: "Small (<$2B)", min: 0, max: 2e9 },
];

// HappyTrader (and any external deep-link) speaks a stable, public slug
// vocabulary. These maps translate to/from our internal window + theme keys.
// Keep these slugs stable — they are a published interface.
const TAB_FROM_SLUG: Record<string, string> = {
  today: "today",
  "this-week": "week",
  "last-week": "last_week",
  upcoming: "upcoming",
};
const TAB_TO_SLUG: Record<string, string> = {
  today: "today",
  week: "this-week",
  last_week: "last-week",
  upcoming: "upcoming",
};
const THEME_FROM_SLUG: Record<string, string> = {
  ai: "ai_tech",
  space: "space",
  quantum: "quantum",
  semis: "semis_hardware",
};
const THEME_TO_SLUG: Record<string, string> = {
  ai_tech: "ai",
  space: "space",
  quantum: "quantum",
  semis_hardware: "semis",
};

const DEFAULT_WINDOW = "upcoming";

export default function DashboardPage() {
  const [windowKey, setWindowKey] = useState(DEFAULT_WINDOW);
  const [theme, setTheme] = useState<string | null>(null);
  const [focusSymbol, setFocusSymbol] = useState<string | null>(null);
  const [themes, setThemes] = useState<Theme[]>([]);
  const [cards, setCards] = useState<EarningsCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sector, setSector] = useState<string | null>(null);
  const [capBucket, setCapBucket] = useState<string | null>(null);
  // Gate data fetching until we've read the inbound deep-link params, so we
  // fetch once with the right state instead of flashing the default view.
  const [paramsReady, setParamsReady] = useState(false);

  useEffect(() => {
    api.themes().then(setThemes).catch(() => setThemes([]));
  }, []);

  // Read inbound deep-link params on mount. Anything unknown/malformed is
  // ignored and we fall through to the normal calendar — never an error.
  useEffect(() => {
    try {
      const sp = new URLSearchParams(window.location.search);

      const tabSlug = (sp.get("tab") ?? "").trim().toLowerCase();
      if (TAB_FROM_SLUG[tabSlug]) setWindowKey(TAB_FROM_SLUG[tabSlug]);

      const themeSlug = (sp.get("theme") ?? "").trim().toLowerCase();
      if (THEME_FROM_SLUG[themeSlug]) setTheme(THEME_FROM_SLUG[themeSlug]);

      const sym = (sp.get("symbol") ?? "").trim().toUpperCase();
      if (sym) setFocusSymbol(sym);
    } catch {
      // Ignore — render the default calendar.
    } finally {
      setParamsReady(true);
    }
  }, []);

  // Symbol focus wins over theme: when a symbol is requested we fetch the
  // whole window (no theme filter) so the ticker can be found regardless.
  useEffect(() => {
    if (!paramsReady) return;
    setLoading(true);
    setError(null);
    const themeArg = focusSymbol ? undefined : theme ?? undefined;
    api
      .earnings(windowKey, themeArg)
      .then((r) => setCards(r.cards))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [paramsReady, windowKey, theme, focusSymbol]);

  // Mirror UI state back into the URL so links are shareable both directions.
  // Preserves any unrelated params (e.g. ref=happytrader) for attribution.
  useEffect(() => {
    if (!paramsReady) return;
    try {
      const sp = new URLSearchParams(window.location.search);
      sp.set("tab", TAB_TO_SLUG[windowKey] ?? windowKey);
      if (focusSymbol) sp.set("symbol", focusSymbol);
      else sp.delete("symbol");
      if (theme) sp.set("theme", THEME_TO_SLUG[theme] ?? theme);
      else sp.delete("theme");
      const qs = sp.toString();
      window.history.replaceState(null, "", qs ? `/?${qs}` : "/");
    } catch {
      // Non-fatal — URL sync is a convenience only.
    }
  }, [paramsReady, windowKey, theme, focusSymbol]);

  const selectWindow = (key: string) => {
    setWindowKey(key);
    setFocusSymbol(null);
  };
  const selectTheme = (key: string | null) => {
    setTheme(key);
    setFocusSymbol(null);
  };

  const focusedCards = focusSymbol
    ? cards.filter((c) => c.ticker.toUpperCase() === focusSymbol)
    : cards;
  const symbolMissing = Boolean(focusSymbol) && focusedCards.length === 0;
  // If the focused symbol has no report in this window, fall back to the full
  // (unfiltered) calendar rather than showing an empty/error state.
  const shownCards = symbolMissing ? cards : focusedCards;

  // Sector list is derived from what's actually in this window so we never
  // offer a filter that would return nothing.
  const sectors = useMemo(
    () =>
      Array.from(
        new Set(shownCards.map((c) => c.sector).filter((s): s is string => Boolean(s)))
      ).sort(),
    [shownCards]
  );

  // Drop a sector filter that no longer exists in the current window/theme so
  // switching tabs never strands the user on an empty list.
  useEffect(() => {
    if (sector && !sectors.includes(sector)) setSector(null);
  }, [sector, sectors]);

  // Filter first (sector + market cap), then sort. Sorting happens per-group
  // below for the grouped view, but this is the flat, filtered, sorted list.
  const filteredCards = useMemo(() => {
    const bucket = CAP_BUCKETS.find((b) => b.key === capBucket);
    return shownCards.filter((c) => {
      if (sector && c.sector !== sector) return false;
      if (bucket) {
        const cap = c.market_cap;
        if (cap === null || cap < bucket.min || cap >= bucket.max) return false;
      }
      return true;
    });
  }, [shownCards, sector, capBucket]);

  const sortedCards = useMemo(
    () => sortCards(filteredCards, sortKey),
    [filteredCards, sortKey]
  );

  const weekGroups = useMemo(
    () =>
      windowKey === "upcoming"
        ? groupByWeek(filteredCards).map((g) => ({
            ...g,
            cards: sortCards(g.cards, sortKey),
          }))
        : null,
    [windowKey, filteredCards, sortKey]
  );

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Earnings calendar</h1>
        <p className="text-sm text-[var(--color-muted)] mt-1">
          Who reports and what the market expects — across AI, space, quantum, and semis.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="inline-flex rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)] p-1">
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              onClick={() => selectWindow(w.key)}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                windowKey === w.key
                  ? "bg-[var(--color-accent)] text-white"
                  : "text-[var(--color-muted)] hover:text-white"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <ThemeChip active={theme === null} onClick={() => selectTheme(null)} label="All themes" />
        {themes.map((t) => (
          <ThemeChip
            key={t.key}
            active={theme === t.key}
            onClick={() => selectTheme(t.key)}
            label={`${t.label}`}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mb-6">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-[var(--color-muted)]">
            Sort
          </span>
          <div className="inline-flex rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)] p-1">
            {SORTS.map((s) => (
              <button
                key={s.key}
                onClick={() => setSortKey(s.key)}
                className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                  sortKey === s.key
                    ? "bg-[var(--color-accent)] text-white"
                    : "text-[var(--color-muted)] hover:text-white"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        <FilterSelect
          label="Sector"
          value={sector ?? ""}
          onChange={(v) => setSector(v || null)}
          options={sectors.map((s) => ({ value: s, label: s }))}
          allLabel="All sectors"
        />

        <FilterSelect
          label="Market cap"
          value={capBucket ?? ""}
          onChange={(v) => setCapBucket(v || null)}
          options={CAP_BUCKETS.map((b) => ({ value: b.key, label: b.label }))}
          allLabel="Any size"
        />

        {(sector || capBucket) && (
          <button
            onClick={() => {
              setSector(null);
              setCapBucket(null);
            }}
            className="text-xs font-medium text-[var(--color-accent)] hover:underline"
          >
            Clear filters
          </button>
        )}
      </div>

      {focusSymbol ? (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)] px-3 py-2 text-sm">
          <span className="text-[var(--color-muted)]">
            {symbolMissing ? (
              <>
                No upcoming earnings for{" "}
                <span className="font-semibold text-white">{focusSymbol}</span> in this
                window — showing the full calendar.
              </>
            ) : (
              <>
                Focused on{" "}
                <span className="font-semibold text-white">{focusSymbol}</span>
              </>
            )}
          </span>
          <button
            onClick={() => setFocusSymbol(null)}
            className="font-medium text-[var(--color-accent)] hover:underline"
          >
            Show all earnings
          </button>
        </div>
      ) : null}

      {loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState
          title="Couldn't reach the API."
          hint="Is the backend running on the configured NEXT_PUBLIC_API_BASE?"
        />
      ) : shownCards.length === 0 ? (
        <EmptyState
          title="No earnings in this window."
          hint="Try a different window, or run a data refresh in the backend (python -m app.refresh)."
        />
      ) : filteredCards.length === 0 ? (
        <EmptyState
          title="No earnings match these filters."
          hint="Try clearing the sector or market-cap filter."
        />
      ) : weekGroups ? (
        <div className="space-y-8">
          {weekGroups.map((g) => (
            <div key={g.label}>
              <div className="flex items-baseline gap-2 mb-3">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--color-muted)]">
                  {g.label}
                </h2>
                <span className="text-xs text-[var(--color-muted)]">
                  {g.cards.length}
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {g.cards.map((c) => (
                  <EarningsCardItem key={`${c.ticker}-${c.date}`} card={c} />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {sortedCards.map((c) => (
            <EarningsCardItem key={`${c.ticker}-${c.date}`} card={c} />
          ))}
        </div>
      )}
    </div>
  );
}

// Order cards within a group (or the flat list). "date" surfaces the soonest
// reports first (implied move breaks ties); the ranked sorts push missing
// values to the bottom so a null never outranks a real number.
function sortCards(cards: EarningsCard[], sortKey: SortKey): EarningsCard[] {
  const byDesc = (key: "implied_move_pct" | "market_cap") => (a: EarningsCard, b: EarningsCard) => {
    const av = a[key];
    const bv = b[key];
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    return bv - av;
  };
  const copy = [...cards];
  if (sortKey === "implied_move") return copy.sort(byDesc("implied_move_pct"));
  if (sortKey === "market_cap") return copy.sort(byDesc("market_cap"));
  return copy.sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? -1 : 1;
    const am = a.implied_move_pct ?? -Infinity;
    const bm = b.implied_move_pct ?? -Infinity;
    return bm - am;
  });
}

// Bucket upcoming cards by calendar week relative to today. Week 0 = "This
// week", week 1 = "Next week", and every later week gets its own group labeled
// by its Monday ("Week of Jul 20") so a big backlog stays scannable instead of
// collapsing into one giant "Later" pile. Weeks start Monday; empties dropped.
function groupByWeek(
  cards: EarningsCard[]
): { label: string; cards: EarningsCard[] }[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const mondayOffset = (today.getDay() + 6) % 7;
  const weekStart = new Date(today);
  weekStart.setDate(today.getDate() - mondayOffset);

  const buckets: Record<number, EarningsCard[]> = {};
  for (const c of cards) {
    const d = new Date(`${c.date}T00:00:00`);
    const diffDays = Math.floor((d.getTime() - weekStart.getTime()) / 86400000);
    const idx = Math.max(0, Math.floor(diffDays / 7));
    (buckets[idx] ??= []).push(c);
  }

  const labelFor = (idx: number) => {
    if (idx === 0) return "This week";
    if (idx === 1) return "Next week";
    const monday = new Date(weekStart);
    monday.setDate(weekStart.getDate() + idx * 7);
    return `Week of ${monday.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    })}`;
  };

  return Object.keys(buckets)
    .map(Number)
    .sort((a, b) => a - b)
    .map((idx) => ({ label: labelFor(idx), cards: buckets[idx] }));
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  allLabel: string;
}) {
  return (
    <label className="flex items-center gap-2">
      <span className="text-xs font-medium uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors bg-[var(--color-panel)] hover:text-white focus:outline-none focus:border-[var(--color-accent)] ${
          value
            ? "border-[var(--color-accent)] text-white"
            : "border-[var(--color-edge)] text-[var(--color-muted)]"
        }`}
      >
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function ThemeChip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
        active
          ? "border-[var(--color-accent)] bg-[var(--color-accent)]/15 text-[var(--color-accent)]"
          : "border-[var(--color-edge)] text-[var(--color-muted)] hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}
