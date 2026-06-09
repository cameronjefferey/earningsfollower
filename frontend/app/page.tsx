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

export default function DashboardPage() {
  const [windowKey, setWindowKey] = useState("upcoming");
  const [theme, setTheme] = useState<string | null>(null);
  const [themes, setThemes] = useState<Theme[]>([]);
  const [cards, setCards] = useState<EarningsCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.themes().then(setThemes).catch(() => setThemes([]));
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .earnings(windowKey, theme ?? undefined)
      .then((r) => setCards(r.cards))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [windowKey, theme]);

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
              onClick={() => setWindowKey(w.key)}
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
        <ThemeChip active={theme === null} onClick={() => setTheme(null)} label="All themes" />
        {themes.map((t) => (
          <ThemeChip
            key={t.key}
            active={theme === t.key}
            onClick={() => setTheme(t.key)}
            label={`${t.label}`}
          />
        ))}
      </div>

      {loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState
          title="Couldn't reach the API."
          hint="Is the backend running on the configured NEXT_PUBLIC_API_BASE?"
        />
      ) : cards.length === 0 ? (
        <EmptyState
          title="No earnings in this window."
          hint="Try a different window, or run a data refresh in the backend (python -m app.refresh)."
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {cards.map((c) => (
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
