import { ThemeTag } from "@/lib/api";
import { InfoTip } from "./InfoTip";

export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-[var(--color-edge)] bg-[var(--color-panel)] ${className}`}
    >
      {children}
    </div>
  );
}

export function Stat({
  label,
  value,
  valueClass = "",
  sub,
  info,
  blur = false,
}: {
  label: string;
  value: React.ReactNode;
  valueClass?: string;
  sub?: React.ReactNode;
  info?: string;
  blur?: boolean;
}) {
  return (
    <div className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
        {label}
        {info ? <InfoTip text={info} /> : null}
      </div>
      <div
        className={`text-lg font-semibold leading-tight tabular ${valueClass}`}
        style={
          blur
            ? { filter: "blur(7px)", userSelect: "none", pointerEvents: "none" }
            : undefined
        }
        aria-hidden={blur || undefined}
      >
        {value}
      </div>
      {sub ? (
        <div
          className="text-xs text-[var(--color-muted)] mt-0.5"
          style={
            blur
              ? { filter: "blur(6px)", userSelect: "none", pointerEvents: "none" }
              : undefined
          }
          aria-hidden={blur || undefined}
        >
          {sub}
        </div>
      ) : null}
    </div>
  );
}

const THEME_COLORS: Record<string, string> = {
  ai_tech: "#5b8cff",
  space: "#b06bff",
  quantum: "#27c6c6",
  semis_hardware: "#f0a85b",
};

export function ThemePill({ theme }: { theme: ThemeTag }) {
  const color = THEME_COLORS[theme.key] ?? "#8a97b1";
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium border"
      style={{
        color,
        borderColor: `${color}55`,
        backgroundColor: `${color}1a`,
      }}
    >
      {theme.label}
    </span>
  );
}

export function VerdictPill({ verdict }: { verdict: string | null | undefined }) {
  if (!verdict) return null;
  const map: Record<string, { label: string; color: string }> = {
    cheap: { label: "Vol cheap", color: "#28c08a" },
    inline: { label: "Vol in-line", color: "#8a97b1" },
    rich: { label: "Vol rich", color: "#f0a85b" },
  };
  const v = map[verdict];
  if (!v) return null;
  return (
    <span
      title="Implied move vs this stock's own historical average move. Rich = options pricing a bigger-than-usual move; Cheap = smaller; In-line = typical."
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium border cursor-help"
      style={{ color: v.color, borderColor: `${v.color}55`, backgroundColor: `${v.color}1a` }}
    >
      {v.label}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-[var(--color-muted)] py-10 justify-center">
      <span className="h-4 w-4 rounded-full border-2 border-[var(--color-edge)] border-t-[var(--color-accent)] animate-spin" />
      {label ?? "Loading…"}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-dashed border-[var(--color-edge)] bg-[var(--color-panel)]/40 px-6 py-12 text-center">
      <div className="text-[var(--color-muted)]">{title}</div>
      {hint ? <div className="text-xs text-[var(--color-muted)] mt-2">{hint}</div> : null}
    </div>
  );
}
