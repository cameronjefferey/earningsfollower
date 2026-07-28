export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function signedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const s = (value * 100).toFixed(digits);
  return value > 0 ? `+${s}%` : `${s}%`;
}

export function moveClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return "text-[var(--color-muted)]";
  if (value > 0) return "text-[var(--color-up)]";
  if (value < 0) return "text-[var(--color-down)]";
  return "text-[var(--color-muted)]";
}

export function marketCap(value: number | null | undefined): string {
  if (!value) return "—";
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(0)}M`;
  return `$${value.toFixed(0)}`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  // Accept both date-only ("2026-07-20") and full timestamps
  // ("2026-07-20T14:30:00[Z]"). Anchor the calendar date to local midnight so a
  // date-only value can't shift a day in negative timezones, and never surface a
  // raw "Invalid Date" — fall back to an em dash.
  const datePart = iso.slice(0, 10);
  const d = /^\d{4}-\d{2}-\d{2}$/.test(datePart)
    ? new Date(datePart + "T00:00:00")
    : new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** Human label for a calendar window key. */
export function windowLabel(key: string): string {
  switch (key) {
    case "all":
      return "All";
    case "today":
      return "Today";
    case "week":
      return "This week";
    case "last_week":
      return "Last week";
    case "upcoming":
      return "Upcoming";
    default:
      return key;
  }
}

export function timingLabel(timing: string | null | undefined): string {
  if (timing === "bmo") return "Before open";
  if (timing === "amc") return "After close";
  return "Time TBD";
}
