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
  const d = new Date(iso + "T00:00:00");
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
