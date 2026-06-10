"use client";

import { useEffect, useState } from "react";
import { api, EarningsCard, Theme } from "@/lib/api";
import { EarningsCardItem } from "@/components/EarningsCardItem";
import { EmptyState, Spinner } from "@/components/ui";

const WINDOWS = [
  { key: "today", label: "Today" },
  { key: "week", label: "This week" },
  { key: "last_week", label: "Last week" },
  { key: "upcoming", label: "Upcoming" },
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

      <div className="flex flex-wrap items-center gap-2 mb-6">
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
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {shownCards.map((c) => (
            <EarningsCardItem key={`${c.ticker}-${c.date}`} card={c} />
          ))}
        </div>
      )}
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
