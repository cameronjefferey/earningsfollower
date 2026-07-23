"use client";

import type { CSSProperties, ReactNode } from "react";

const BLUR_STYLE: CSSProperties = {
  filter: "blur(7px)",
  userSelect: "none",
  pointerEvents: "none",
  display: "inline-block",
  verticalAlign: "bottom",
};

const ZONE_BLUR_STYLE: CSSProperties = {
  filter: "blur(8px)",
  userSelect: "none",
  pointerEvents: "none",
  opacity: 0.85,
};

/** Blur a single value/stat while keeping surrounding chrome readable. */
export function BlurValue({
  active,
  children,
  className = "",
}: {
  active: boolean;
  children: ReactNode;
  className?: string;
}) {
  if (!active) return <>{children}</>;
  return (
    <span className={className} style={BLUR_STYLE} aria-hidden>
      {children}
    </span>
  );
}

/** Soft blur over a denser block (charts, tables of numbers) with a demo chip. */
export function BlurZone({
  active,
  children,
  className = "",
  label = "Sample data",
}: {
  active: boolean;
  children: ReactNode;
  className?: string;
  label?: string;
}) {
  if (!active) return <>{children}</>;
  return (
    <div className={`relative overflow-hidden ${className}`}>
      <div style={ZONE_BLUR_STYLE} aria-hidden>
        {children}
      </div>
      <div
        className="pointer-events-none absolute inset-0 flex items-center justify-center"
        style={{
          background:
            "linear-gradient(180deg, transparent 10%, rgba(10,14,23,0.35) 50%, transparent 90%)",
        }}
      >
        <span className="rounded-md border border-[var(--color-edge)] bg-[var(--color-panel)]/95 px-2.5 py-1 text-[11px] font-medium tracking-wide text-[var(--color-muted)] uppercase">
          {label}
        </span>
      </div>
    </div>
  );
}
