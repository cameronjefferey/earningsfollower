"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, EarningsCard, Theme } from "@/lib/api";
import { CalendarWelcome } from "@/components/CalendarWelcome";
import { DigestStrip } from "@/components/DigestStrip";
import {
  EarningsCardItem,
  EarningsCardSkeleton,
} from "@/components/EarningsCardItem";
import { UpdatedAt } from "@/components/UpdatedAt";
import { EmptyState } from "@/components/ui";
import { windowLabel } from "@/lib/format";

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

// Playbook-aligned conviction tiers (same labels as company page).
const CONVICTION_BUCKETS: { key: string; label: string }[] = [
  { key: "high", label: "High" },
  { key: "medium", label: "Medium" },
  { key: "low", label: "Low" },
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
// Progressive calendar load per tab (Waves/Drift style). Keep batches small so
// local/dev doesn't choke rendering hundreds of cards at once.
const FIRST_BATCH = 18;
const FULL_BATCH = 60;

const THEME_PIN_KEY = "ef.calendar.pinnedThemes";
const DEFAULT_PINNED_THEMES = [
  "ai_tech",
  "space",
  "quantum",
  "semis_hardware",
];
const MAX_PINNED_THEMES = 4;

function loadPinnedThemes(): string[] {
  try {
    const raw = localStorage.getItem(THEME_PIN_KEY);
    if (!raw) return DEFAULT_PINNED_THEMES;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return DEFAULT_PINNED_THEMES;
    const keys = parsed.filter((k): k is string => typeof k === "string").slice(0, MAX_PINNED_THEMES);
    return keys.length ? keys : DEFAULT_PINNED_THEMES;
  } catch {
    return DEFAULT_PINNED_THEMES;
  }
}

export default function DashboardPage() {
  const [windowKey, setWindowKey] = useState(DEFAULT_WINDOW);
  const [theme, setTheme] = useState<string | null>(null);
  const [focusSymbol, setFocusSymbol] = useState<string | null>(null);
  const [themes, setThemes] = useState<Theme[]>([]);
  const [pinnedThemeKeys, setPinnedThemeKeys] = useState<string[]>(DEFAULT_PINNED_THEMES);
  const [cards, setCards] = useState<EarningsCard[]>([]);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [loadedLimit, setLoadedLimit] = useState(FIRST_BATCH);
  const [error, setError] = useState<string | null>(null);
  const [moreError, setMoreError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [selectedSectors, setSelectedSectors] = useState<string[]>([]);
  const [selectedCaps, setSelectedCaps] = useState<string[]>([]);
  const [selectedConvictions, setSelectedConvictions] = useState<string[]>([]);
  // Keep Narrow results collapsed so earnings cards stay above the fold.
  const [filtersOpen, setFiltersOpen] = useState(false);
  // Gate data fetching until we've read the inbound deep-link params, so we
  // fetch once with the right state instead of flashing the default view.
  const [paramsReady, setParamsReady] = useState(false);
  const fetchGen = useRef(0);
  // Cache cards by window so tab switches don't refetch.
  const cacheRef = useRef<
    Record<
      string,
      { cards: EarningsCard[]; limit: number; hasMore: boolean; updatedAt?: string | null }
    >
  >({});

  useEffect(() => {
    setPinnedThemeKeys(loadPinnedThemes());
    api.themes().then(setThemes).catch(() => setThemes([]));
  }, []);

  const themeByKey = useMemo(() => {
    const map = new Map<string, Theme>();
    for (const t of themes) map.set(t.key, t);
    return map;
  }, [themes]);

  const pinnedThemes = useMemo(() => {
    const fromPins = pinnedThemeKeys
      .map((k) => themeByKey.get(k))
      .filter((t): t is Theme => Boolean(t));
    // Deep-link / active filter outside the pin set still deserves a chip.
    if (theme && !pinnedThemeKeys.includes(theme)) {
      const extra = themeByKey.get(theme);
      if (extra) return [...fromPins, extra];
    }
    return fromPins;
  }, [pinnedThemeKeys, themeByKey, theme]);

  const persistPinnedThemes = (keys: string[]) => {
    const next = keys.slice(0, MAX_PINNED_THEMES);
    setPinnedThemeKeys(next);
    try {
      localStorage.setItem(THEME_PIN_KEY, JSON.stringify(next));
    } catch {
      /* ignore quota / private mode */
    }
    if (theme && !next.includes(theme)) setTheme(null);
  };

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

  // Progressive fetch for the active tab only. Tab switches use a small cache;
  // theme/sector filters stay client-side within the loaded window.
  useEffect(() => {
    if (!paramsReady) return;

    const cached = cacheRef.current[windowKey];
    if (cached) {
      setCards(cached.cards);
      setHasMore(cached.hasMore);
      setLoadedLimit(cached.limit);
      setUpdatedAt(cached.updatedAt ?? null);
      setLoading(false);
      setLoadingMore(false);
      setError(null);
      return;
    }

    const gen = ++fetchGen.current;
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setMoreError(null);
    setHasMore(false);
    setLoadedLimit(FIRST_BATCH);

    api
      .earnings(windowKey, undefined, FIRST_BATCH)
      .then(async (first) => {
        if (gen !== fetchGen.current) return;
        setCards(first.cards);
        setHasMore(Boolean(first.has_more));
        setLoadedLimit(first.limit ?? FIRST_BATCH);
        setUpdatedAt(first.updated_at ?? null);
        setLoading(false);
        cacheRef.current[windowKey] = {
          cards: first.cards,
          limit: first.limit ?? FIRST_BATCH,
          hasMore: Boolean(first.has_more),
          updatedAt: first.updated_at ?? null,
        };

        if (!first.has_more) return;

        setLoadingMore(true);
        try {
          const full = await api.earnings(windowKey, undefined, FULL_BATCH);
          if (gen !== fetchGen.current) return;
          setCards(full.cards);
          setHasMore(Boolean(full.has_more));
          setLoadedLimit(full.limit ?? FULL_BATCH);
          setUpdatedAt(full.updated_at ?? null);
          cacheRef.current[windowKey] = {
            cards: full.cards,
            limit: full.limit ?? FULL_BATCH,
            hasMore: Boolean(full.has_more),
            updatedAt: full.updated_at ?? null,
          };
        } catch {
          /* keep the first batch if the expand fails */
        } finally {
          if (gen === fetchGen.current) setLoadingMore(false);
        }
      })
      .catch((e) => {
        if (gen !== fetchGen.current) return;
        setError(String(e));
        setLoading(false);
      });

    return () => {
      fetchGen.current += 1;
    };
  }, [paramsReady, windowKey]);

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

  // Cards are fetched per active tab. Theme / sector / cap stay client-side.
  // Symbol search ignores theme so a ticker is findable within the loaded tab.
  const themeCards = useMemo(() => {
    if (!theme || focusSymbol) return cards;
    return cards.filter((c) => c.themes.some((t) => t.key === theme));
  }, [cards, theme, focusSymbol]);

  const focusedCards = focusSymbol
    ? cards.filter((c) => c.ticker.toUpperCase().includes(focusSymbol))
    : themeCards;
  const symbolMissing = Boolean(focusSymbol) && focusedCards.length === 0;
  const shownCards = symbolMissing ? themeCards : focusedCards;

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

  // Filter first (sector + market cap + conviction), then sort. Sorting happens
  // per-group below for the grouped view, but this is the flat, filtered,
  // sorted list. An empty selection means "no filter" (match everything);
  // otherwise a card must match at least one selected bucket.
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
      if (
        selectedConvictions.length &&
        !(c.conviction && selectedConvictions.includes(c.conviction))
      ) {
        return false;
      }
      return true;
    });
  }, [shownCards, selectedSectors, selectedCaps, selectedConvictions]);

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

  const resultsSummary = useMemo(() => {
    const parts = [
      `Showing ${filteredCards.length}`,
      windowLabel(windowKey),
    ];
    if (theme) {
      parts.push(themeByKey.get(theme)?.label ?? theme);
    }
    if (focusSymbol) parts.push(focusSymbol);
    if (selectedSectors.length === 1) parts.push(selectedSectors[0]);
    else if (selectedSectors.length > 1) parts.push(`${selectedSectors.length} sectors`);
    if (selectedCaps.length === 1) {
      parts.push(
        CAP_BUCKETS.find((b) => b.key === selectedCaps[0])?.label ?? "cap filter"
      );
    } else if (selectedCaps.length > 1) {
      parts.push(`${selectedCaps.length} size filters`);
    }
    if (selectedConvictions.length === 1) {
      const label =
        CONVICTION_BUCKETS.find((b) => b.key === selectedConvictions[0])?.label ??
        selectedConvictions[0];
      parts.push(`${label} conviction`);
    } else if (selectedConvictions.length > 1) {
      parts.push(`${selectedConvictions.length} conviction levels`);
    }
    return parts.join(" · ");
  }, [
    filteredCards.length,
    windowKey,
    theme,
    themeByKey,
    focusSymbol,
    selectedSectors,
    selectedCaps,
    selectedConvictions,
  ]);

  const activeFilterCount =
    (focusSymbol ? 1 : 0) +
    selectedSectors.length +
    selectedCaps.length +
    selectedConvictions.length +
    (sortKey !== "date" ? 1 : 0);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
          Earnings calendar
        </h1>
        <UpdatedAt value={updatedAt} />
      </div>

      <CalendarWelcome />

      <DigestStrip />

      <div className="mb-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex flex-wrap rounded-lg bg-[var(--color-panel)]/70 p-1 gap-0.5">
            {WINDOWS.map((w) => (
              <button
                key={w.key}
                type="button"
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
          <button
            type="button"
            onClick={() => setFiltersOpen((o) => !o)}
            aria-expanded={filtersOpen}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
              filtersOpen || activeFilterCount > 0
                ? "border-[var(--color-accent)]/50 text-white"
                : "border-[var(--color-edge)]/70 text-[var(--color-muted)] hover:text-white"
            }`}
          >
            Filters
            {activeFilterCount > 0 ? (
              <span className="rounded-md bg-[var(--color-accent)]/20 px-1.5 text-xs text-[var(--color-accent)] tabular">
                {activeFilterCount}
              </span>
            ) : null}
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ThemeChip
            active={theme === null}
            onClick={() => selectTheme(null)}
            label="All themes"
          />
          {pinnedThemes.map((t) => (
            <ThemeChip
              key={t.key}
              active={theme === t.key}
              onClick={() => selectTheme(t.key)}
              label={t.label}
            />
          ))}
          <ThemePinPicker
            allThemes={themes}
            pinnedKeys={pinnedThemeKeys}
            onChange={persistPinnedThemes}
          />
        </div>

        {filtersOpen ? (
          <div className="rounded-xl bg-[var(--color-panel)]/35 p-3 sm:p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
              <div className="text-sm font-medium text-white">Narrow results</div>
              {(theme ||
                focusSymbol ||
                selectedSectors.length > 0 ||
                selectedCaps.length > 0 ||
                selectedConvictions.length > 0 ||
                sortKey !== "date") && (
                <button
                  type="button"
                  onClick={() => {
                    selectTheme(null);
                    setFocusSymbol(null);
                    setSelectedSectors([]);
                    setSelectedCaps([]);
                    setSelectedConvictions([]);
                    setSortKey("date");
                  }}
                  className="text-sm text-[var(--color-accent)] hover:underline"
                >
                  Clear all
                </button>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-[var(--color-muted)]">
                  Search ticker
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
                    placeholder="e.g. NVDA"
                    spellCheck={false}
                    autoCapitalize="characters"
                    className={`w-full rounded-lg border bg-transparent py-2 pl-3 pr-8 text-sm font-medium text-white placeholder:text-[var(--color-muted)] focus:outline-none focus:border-[var(--color-accent)] ${
                      focusSymbol
                        ? "border-[var(--color-accent)]"
                        : "border-[var(--color-edge)]/70"
                    }`}
                  />
                  {focusSymbol ? (
                    <button
                      type="button"
                      onClick={() => setFocusSymbol(null)}
                      aria-label="Clear symbol search"
                      className="absolute right-2 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded text-[var(--color-muted)] hover:text-white"
                    >
                      <svg viewBox="0 0 10 10" className="h-2.5 w-2.5" fill="none" aria-hidden>
                        <path
                          d="M2 2 8 8 M8 2 2 8"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                        />
                      </svg>
                    </button>
                  ) : null}
                </div>
              </label>

              <div className="space-y-1.5">
                <div className="text-xs font-medium text-[var(--color-muted)]">Sort by</div>
                <div className="inline-flex w-full rounded-lg border border-[var(--color-edge)]/70 bg-transparent p-1">
                  {SORTS.map((s) => (
                    <button
                      key={s.key}
                      type="button"
                      onClick={() => setSortKey(s.key)}
                      className={`flex-1 px-2 py-1.5 rounded-md text-xs sm:text-sm font-medium transition-colors ${
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

              <MultiSelect
                label="Conviction"
                selected={selectedConvictions}
                onChange={setSelectedConvictions}
                options={CONVICTION_BUCKETS.map((b) => ({
                  value: b.key,
                  label: b.label,
                }))}
                allLabel="Any conviction"
              />
            </div>
          </div>
        ) : null}
      </div>

      {!loading && !error ? (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 text-sm text-[var(--color-muted)]">
          <p>
            {symbolMissing ? (
              <>
                No earnings for{" "}
                <span className="text-white font-medium">{focusSymbol}</span> in this
                tab — try All or another window.
              </>
            ) : (
              <span>{resultsSummary}</span>
            )}
          </p>
          {focusSymbol && !symbolMissing ? (
            <button
              type="button"
              onClick={() => setFocusSymbol(null)}
              className="text-[var(--color-accent)] hover:underline"
            >
              Clear search
            </button>
          ) : null}
        </div>
      ) : null}

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <EarningsCardSkeleton key={i} />
          ))}
        </div>
      ) : error ? (
        <EmptyState
          title="Couldn't reach the API."
          hint="Is the backend running on the configured NEXT_PUBLIC_API_BASE?"
        />
      ) : shownCards.length === 0 ? (
        <EmptyState
          title="No earnings in this window."
          hint="Try a different window, or check back after the next data refresh."
        />
      ) : filteredCards.length === 0 ? (
        <EmptyState
          title="No earnings match these filters."
          hint="Try clearing sector, market cap, conviction, or theme."
        />
      ) : weekGroups ? (
        <div className="space-y-10">
          {weekGroups.map((g) => (
            <div key={g.label}>
              <div className="flex items-baseline gap-2.5 mb-4">
                <h2 className="text-sm font-semibold tracking-wide text-white">
                  {g.label}
                </h2>
                <span className="text-xs text-[var(--color-muted)] tabular">
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

      {loadingMore ? (
        <div className="mt-4 flex items-center justify-center gap-2 text-sm text-[var(--color-muted)]">
          <span className="h-3.5 w-3.5 rounded-full border-2 border-[var(--color-edge)] border-t-[var(--color-accent)] animate-spin" />
          Loading more names…
        </div>
      ) : null}
      {moreError ? (
        <p className="mt-3 text-center text-sm text-[var(--color-muted)]">{moreError}</p>
      ) : null}
      {hasMore && !loadingMore ? (
        <div className="mt-4 flex justify-center">
          <button
            type="button"
            onClick={() => {
              const next = Math.min(loadedLimit + 60, 400);
              const gen = ++fetchGen.current;
              setLoadingMore(true);
              setMoreError(null);
              api
                .earnings(windowKey, undefined, next)
                .then((full) => {
                  if (gen !== fetchGen.current) return;
                  setCards(full.cards);
                  setHasMore(Boolean(full.has_more));
                  setLoadedLimit(full.limit ?? next);
                  setUpdatedAt(full.updated_at ?? null);
                  cacheRef.current[windowKey] = {
                    cards: full.cards,
                    limit: full.limit ?? next,
                    hasMore: Boolean(full.has_more),
                    updatedAt: full.updated_at ?? null,
                  };
                })
                .catch(() => {
                  if (gen !== fetchGen.current) return;
                  setMoreError("Couldn't load more — try again.");
                })
                .finally(() => {
                  if (gen === fetchGen.current) setLoadingMore(false);
                });
            }}
            className="px-4 py-2 rounded-lg text-sm font-medium border border-[var(--color-edge)] hover:bg-[var(--color-panel-2)]"
          >
            Load more
          </button>
        </div>
      ) : null}
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
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-[var(--color-muted)]">{label}</div>
      <div className="relative" ref={ref}>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className={`inline-flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2.5 text-sm font-medium transition-colors bg-transparent hover:text-white focus:outline-none focus:border-[var(--color-accent)] ${
            count > 0
              ? "border-[var(--color-accent)] text-white"
              : "border-[var(--color-edge)]/70 text-[var(--color-muted)]"
          }`}
        >
          <span className="truncate">{summary}</span>
          <svg
            className={`h-3.5 w-3.5 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
            viewBox="0 0 12 12"
            fill="none"
            aria-hidden="true"
          >
            <path d="M3 4.5 6 7.5 9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        {open && (
          <div className="absolute left-0 z-20 mt-1.5 max-h-72 w-full min-w-[14rem] overflow-auto rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)] p-1.5 shadow-lg">
            {options.length === 0 ? (
              <div className="px-2.5 py-2 text-sm text-[var(--color-muted)]">
                Nothing to filter
              </div>
            ) : (
              <>
                {count > 0 && (
                  <button
                    type="button"
                    onClick={() => onChange([])}
                    className="w-full rounded-md px-2.5 py-2 text-left text-sm font-medium text-[var(--color-accent)] hover:bg-[var(--color-panel-2)]"
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
                      className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm hover:bg-[var(--color-panel-2)]"
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
      type="button"
      onClick={onClick}
      className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
        active
          ? "border-[var(--color-accent)] bg-[var(--color-accent)]/15 text-[var(--color-accent)]"
          : "border-[var(--color-edge)] text-[var(--color-muted)] hover:text-white hover:border-[var(--color-muted)]"
      }`}
    >
      {label}
    </button>
  );
}

/** Pick up to four themes to keep on the calendar chip row. */
function ThemePinPicker({
  allThemes,
  pinnedKeys,
  onChange,
}: {
  allThemes: Theme[];
  pinnedKeys: string[];
  onChange: (keys: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

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

  const toggle = (key: string) => {
    if (pinnedKeys.includes(key)) {
      onChange(pinnedKeys.filter((k) => k !== key));
      return;
    }
    if (pinnedKeys.length >= MAX_PINNED_THEMES) return;
    onChange([...pinnedKeys, key]);
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-sm text-[var(--color-accent)] hover:underline"
        title="Choose which themes appear here"
      >
        Edit themes
      </button>
      {open ? (
        <div className="absolute right-0 top-full mt-2 z-30 w-72 rounded-xl border border-[var(--color-edge)] bg-[var(--color-panel)] shadow-lg p-3">
          <div className="px-1 pb-2 text-xs text-[var(--color-muted)] flex justify-between gap-3">
            <span>Pin up to {MAX_PINNED_THEMES} themes</span>
            <span className="tabular-nums">
              {pinnedKeys.length}/{MAX_PINNED_THEMES}
            </span>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {allThemes.map((t) => {
              const checked = pinnedKeys.includes(t.key);
              const atCap = !checked && pinnedKeys.length >= MAX_PINNED_THEMES;
              return (
                <button
                  key={t.key}
                  type="button"
                  disabled={atCap}
                  onClick={() => toggle(t.key)}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left text-xs ${
                    atCap
                      ? "opacity-40 cursor-not-allowed"
                      : "hover:bg-[var(--color-panel-2)]"
                  }`}
                >
                  <span
                    className={`flex h-3.5 w-3.5 items-center justify-center rounded border ${
                      checked
                        ? "border-[var(--color-accent)] bg-[var(--color-accent)] text-white"
                        : "border-[var(--color-edge)]"
                    }`}
                  >
                    {checked ? (
                      <svg viewBox="0 0 10 10" className="h-2.5 w-2.5" fill="none" aria-hidden>
                        <path
                          d="M2 5 4 7 8 3"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    ) : null}
                  </span>
                  <span className={checked ? "text-white" : "text-[var(--color-muted)]"}>
                    {t.label}
                  </span>
                  <span className="ml-auto text-[var(--color-muted)] tabular-nums">
                    {t.ticker_count}
                  </span>
                </button>
              );
            })}
          </div>
          <button
            type="button"
            onClick={() => onChange(DEFAULT_PINNED_THEMES)}
            className="mt-1 w-full px-2 py-1.5 text-[11px] text-[var(--color-muted)] hover:text-white text-left"
          >
            Reset to defaults
          </button>
        </div>
      ) : null}
    </div>
  );
}
