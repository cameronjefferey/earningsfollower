"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, EarningsCard, Theme } from "@/lib/api";
import { EarningsCardItem } from "@/components/EarningsCardItem";
import { EmptyState, Spinner } from "@/components/ui";

// The tabs are client-side date filters over a single fetched span, not
// separate requests — switching is instant and search spans every group.
const WINDOWS = [
  { key: "all", label: "All" },
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
  all: "all",
  today: "today",
  "this-week": "week",
  "last-week": "last_week",
  upcoming: "upcoming",
};
const TAB_TO_SLUG: Record<string, string> = {
  all: "all",
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
  const [selectedSectors, setSelectedSectors] = useState<string[]>([]);
  const [selectedCaps, setSelectedCaps] = useState<string[]>([]);
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

  // Fetch the whole span ("all") once — every tab is then a client-side date
  // filter over this set, so switching tabs is instant and search spans them
  // all. Only theme (server-filtered) and focus (ignores theme to find any
  // ticker) trigger a refetch; the window tab never does. Keying off hasFocus
  // (a boolean) means typing in the search box doesn't refetch per keystroke.
  const hasFocus = Boolean(focusSymbol);
  useEffect(() => {
    if (!paramsReady) return;
    setLoading(true);
    setError(null);
    const themeArg = hasFocus ? undefined : theme ?? undefined;
    api
      .earnings("all", themeArg)
      .then((r) => setCards(r.cards))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [paramsReady, theme, hasFocus]);

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

  // The selected tab is a client-side date filter over the loaded span. "all"
  // (r === null) applies no date restriction. Cards carry ISO date strings, so
  // we compare lexicographically against the ISO range bounds.
  const windowCards = useMemo(() => {
    const r = windowRange(windowKey);
    if (!r) return cards;
    const [start, end] = r;
    return cards.filter((c) => c.date >= start && c.date <= end);
  }, [cards, windowKey]);

  // A symbol search spans every tab: match against the full loaded span, not
  // just the current window. Substring so it narrows as you type (e.g. "NV" →
  // NVDA); a full ticker from a deep-link still resolves to just that name.
  const focusedCards = focusSymbol
    ? cards.filter((c) => c.ticker.toUpperCase().includes(focusSymbol))
    : windowCards;
  const symbolMissing = Boolean(focusSymbol) && focusedCards.length === 0;
  // If the search matches nothing anywhere, fall back to the current tab's
  // cards rather than showing an empty/error state.
  const shownCards = symbolMissing ? windowCards : focusedCards;

  // Sector list is derived from what's actually in this window so we never
  // offer a filter that would return nothing.
  const sectors = useMemo(
    () =>
      Array.from(
        new Set(shownCards.map((c) => c.sector).filter((s): s is string => Boolean(s)))
      ).sort(),
    [shownCards]
  );

  // Drop any selected sectors that no longer exist in the current window/theme
  // so switching tabs never strands the user on an empty list.
  useEffect(() => {
    setSelectedSectors((prev) => {
      const next = prev.filter((s) => sectors.includes(s));
      return next.length === prev.length ? prev : next;
    });
  }, [sectors]);

  // Filter first (sector + market cap), then sort. Sorting happens per-group
  // below for the grouped view, but this is the flat, filtered, sorted list.
  // An empty selection means "no filter" (match everything); otherwise a card
  // must match at least one of the selected sectors / cap buckets.
  const filteredCards = useMemo(() => {
    const buckets = CAP_BUCKETS.filter((b) => selectedCaps.includes(b.key));
    return shownCards.filter((c) => {
      if (selectedSectors.length && !(c.sector && selectedSectors.includes(c.sector)))
        return false;
      if (buckets.length) {
        const cap = c.market_cap;
        const inBucket =
          cap !== null && buckets.some((b) => cap >= b.min && cap < b.max);
        if (!inBucket) return false;
      }
      return true;
    });
  }, [shownCards, selectedSectors, selectedCaps]);

  const sortedCards = useMemo(
    () => sortCards(filteredCards, sortKey),
    [filteredCards, sortKey]
  );

  // Group by week for the broad views ("Upcoming" and "All"), but not while a
  // symbol search is active — search results are a flat cross-tab list.
  const weekGroups = useMemo(
    () =>
      !focusSymbol && (windowKey === "upcoming" || windowKey === "all")
        ? groupByWeek(filteredCards).map((g) => ({
            ...g,
            cards: sortCards(g.cards, sortKey),
          }))
        : null,
    [windowKey, focusSymbol, filteredCards, sortKey]
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
            Symbol
          </span>
          <div className="relative">
            <input
              type="text"
              value={focusSymbol ?? ""}
              onChange={(e) =>
                setFocusSymbol(
                  e.target.value.toUpperCase().replace(/[^A-Z.]/g, "") || null
                )
              }
              placeholder="Search ticker"
              spellCheck={false}
              autoCapitalize="characters"
              className={`w-36 rounded-lg border bg-[var(--color-panel)] py-1 pl-2.5 pr-6 text-xs font-medium text-white placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--color-accent)] ${
                focusSymbol ? "border-[var(--color-accent)]" : "border-[var(--color-edge)]"
              }`}
            />
            {focusSymbol && (
              <button
                type="button"
                onClick={() => setFocusSymbol(null)}
                aria-label="Clear symbol search"
                className="absolute right-1 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center rounded text-[var(--color-muted)] hover:text-white"
              >
                <svg viewBox="0 0 10 10" className="h-2.5 w-2.5" fill="none" aria-hidden="true">
                  <path d="M2 2 8 8 M8 2 2 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </button>
            )}
          </div>
        </div>

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

        <MultiSelect
          label="Sector"
          selected={selectedSectors}
          onChange={setSelectedSectors}
          options={sectors.map((s) => ({ value: s, label: s }))}
          allLabel="All sectors"
        />

        <MultiSelect
          label="Market cap"
          selected={selectedCaps}
          onChange={setSelectedCaps}
          options={CAP_BUCKETS.map((b) => ({ value: b.key, label: b.label }))}
          allLabel="Any size"
        />

        {(selectedSectors.length > 0 || selectedCaps.length > 0) && (
          <button
            onClick={() => {
              setSelectedSectors([]);
              setSelectedCaps([]);
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
                No earnings for{" "}
                <span className="font-semibold text-white">{focusSymbol}</span> in the
                loaded calendar range.
              </>
            ) : (
              <>
                Showing{" "}
                <span className="font-semibold text-white">{focusSymbol}</span> across all
                tabs
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

// Bucket cards by calendar week relative to today. Week -1 = "Last week"
// (the "All" view reaches into the past), 0 = "This week", 1 = "Next week",
// and every other week gets its own group labeled by its Monday ("Week of Jul
// 20") so a big backlog stays scannable instead of collapsing into one giant
// pile. Weeks start Monday; empty weeks are dropped.
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
    const idx = Math.floor(diffDays / 7);
    (buckets[idx] ??= []).push(c);
  }

  const labelFor = (idx: number) => {
    if (idx === -1) return "Last week";
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

// Client-side mirror of the backend's date_range_for_window, so the window
// tabs filter the already-loaded span without a refetch. Returns ISO date
// bounds [start, end] (inclusive), or null for "all" (no date restriction).
// Weeks start Monday, matching the backend.
function windowRange(key: string): [string, string] | null {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const dow = (today.getDay() + 6) % 7; // Monday = 0
  const shift = (base: Date, days: number) => {
    const d = new Date(base);
    d.setDate(base.getDate() + days);
    return d;
  };
  if (key === "today") return [isoDate(today), isoDate(today)];
  if (key === "week") {
    const s = shift(today, -dow);
    return [isoDate(s), isoDate(shift(s, 6))];
  }
  if (key === "last_week") {
    const s = shift(today, -dow - 7);
    return [isoDate(s), isoDate(shift(s, 6))];
  }
  if (key === "upcoming") {
    const nextMonday = shift(today, 7 - dow);
    return [isoDate(nextMonday), isoDate(shift(nextMonday, 13))];
  }
  return null; // "all"
}

function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function MultiSelect({
  label,
  selected,
  onChange,
  options,
  allLabel,
}: {
  label: string;
  selected: string[];
  onChange: (values: string[]) => void;
  options: { value: string; label: string }[];
  allLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click / Escape so the panel behaves like a native menu.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toggle = (value: string) =>
    onChange(
      selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value]
    );

  const count = selected.length;
  const summary =
    count === 0
      ? allLabel
      : count === 1
      ? options.find((o) => o.value === selected[0])?.label ?? `${count} selected`
      : `${count} selected`;

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </span>
      <div className="relative" ref={ref}>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors bg-[var(--color-panel)] hover:text-white focus:outline-none focus:border-[var(--color-accent)] ${
            count > 0
              ? "border-[var(--color-accent)] text-white"
              : "border-[var(--color-edge)] text-[var(--color-muted)]"
          }`}
        >
          <span className="max-w-[10rem] truncate">{summary}</span>
          <svg
            className={`h-3 w-3 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
            viewBox="0 0 12 12"
            fill="none"
            aria-hidden="true"
          >
            <path d="M3 4.5 6 7.5 9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        {open && (
          <div className="absolute left-0 z-20 mt-1 max-h-72 w-56 overflow-auto rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)] p-1 shadow-lg">
            {options.length === 0 ? (
              <div className="px-2 py-1.5 text-xs text-[var(--color-muted)]">
                Nothing to filter
              </div>
            ) : (
              <>
                {count > 0 && (
                  <button
                    type="button"
                    onClick={() => onChange([])}
                    className="w-full rounded-md px-2 py-1.5 text-left text-xs font-medium text-[var(--color-accent)] hover:bg-[var(--color-panel-2)]"
                  >
                    Clear {label.toLowerCase()}
                  </button>
                )}
                {options.map((o) => {
                  const checked = selected.includes(o.value);
                  return (
                    <button
                      key={o.value}
                      type="button"
                      onClick={() => toggle(o.value)}
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-[var(--color-panel-2)]"
                    >
                      <span
                        className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded border ${
                          checked
                            ? "border-[var(--color-accent)] bg-[var(--color-accent)] text-white"
                            : "border-[var(--color-edge)]"
                        }`}
                      >
                        {checked && (
                          <svg viewBox="0 0 10 10" className="h-2.5 w-2.5" fill="none" aria-hidden="true">
                            <path d="M2 5 4 7 8 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        )}
                      </span>
                      <span className={checked ? "text-white" : "text-[var(--color-muted)]"}>
                        {o.label}
                      </span>
                    </button>
                  );
                })}
              </>
            )}
          </div>
        )}
      </div>
    </div>
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
