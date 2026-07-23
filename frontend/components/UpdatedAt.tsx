"use client";

export function UpdatedAt({ value }: { value?: string | null }) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  const label = d.toLocaleString("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
  return (
    <p className="text-xs text-[var(--color-muted)] mt-1">Updated {label}</p>
  );
}
