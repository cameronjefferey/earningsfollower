"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";

export function PaywallBanner({
  note,
  title = "Sample preview",
  ctaLabel,
  badge = "Sample",
}: {
  note?: string | null;
  title?: string;
  ctaLabel?: string;
  /** Shown in the corner chip - "Sample" for demo boards, not "Pro". */
  badge?: string;
}) {
  const pathname = usePathname();
  const { data: session } = useSession();
  const next = pathname && pathname !== "/" ? pathname : "/boards";
  const pricingHref = `/pricing?next=${encodeURIComponent(next)}`;
  const ctaHref = session ? pricingHref : `/login?next=${encodeURIComponent(pricingHref)}`;
  const label = ctaLabel ?? (session ? "Get Pro" : "Sign in for Pro");

  return (
    <div className="mb-6 rounded-xl border border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 px-4 py-4 flex flex-col sm:flex-row sm:items-center gap-3 justify-between">
      <div className="min-w-0 flex items-start gap-3">
        <span className="shrink-0 mt-0.5 rounded-md bg-[var(--color-accent)]/20 text-[var(--color-accent)] text-[10px] font-bold uppercase tracking-wider px-2 py-1">
          {badge}
        </span>
        <div>
          <div className="text-sm font-semibold tracking-tight">{title}</div>
          <p className="text-sm text-[var(--color-muted)] mt-1 leading-relaxed">
            {note ||
              "This is demo data so you can see the layout - not today's live book. Pro unlocks live Waves and Drift."}
          </p>
        </div>
      </div>
      <Link
        href={ctaHref}
        className="shrink-0 inline-flex items-center justify-center rounded-lg bg-[var(--color-accent)] text-white text-sm font-medium px-4 py-2.5 hover:opacity-90"
      >
        {label}
      </Link>
    </div>
  );
}

/** Soft lock strip at the bottom of a preview section. */
export function PaywallFade({
  label = "Unlock the live board with Pro",
}: {
  label?: string;
}) {
  const pathname = usePathname();
  const { data: session } = useSession();
  const next = pathname && pathname !== "/" ? pathname : "/boards";
  const pricingHref = `/pricing?next=${encodeURIComponent(next)}`;
  const ctaHref = session ? pricingHref : `/login?next=${encodeURIComponent(pricingHref)}`;

  return (
    <div className="relative mt-2 pt-10 -mb-2">
      <div className="pointer-events-none absolute inset-x-0 -top-16 h-16 bg-gradient-to-b from-transparent to-[var(--color-ink)]" />
      <div className="rounded-xl border border-[var(--color-edge)] bg-[var(--color-panel)]/80 px-4 py-4 text-center">
        <p className="text-sm text-[var(--color-muted)] mb-3">{label}</p>
        <Link
          href={ctaHref}
          className="inline-flex items-center justify-center rounded-lg bg-[var(--color-accent)] text-white text-sm font-medium px-4 py-2 hover:opacity-90"
        >
          See pricing
        </Link>
      </div>
    </div>
  );
}
