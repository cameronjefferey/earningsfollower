"use client";

import type { SampleTier } from "@/lib/api";

const MAP: Record<SampleTier, { label: string; color: string }> = {
  thin: { label: "thin history", color: "#f0a85b" },
  ok: { label: "ok sample", color: "#8a97b1" },
  solid: { label: "solid sample", color: "#28c08a" },
};

export function SampleTierBadge({ tier }: { tier?: SampleTier | null }) {
  if (!tier) return null;
  const v = MAP[tier];
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold border uppercase tracking-wide"
      style={{ color: v.color, borderColor: `${v.color}55`, backgroundColor: `${v.color}1a` }}
      title={
        tier === "thin"
          ? "Fewer than 5 similar past events — treat cautiously"
          : tier === "ok"
            ? "5–8 similar past events"
            : "9+ similar past events"
      }
    >
      {v.label}
    </span>
  );
}
