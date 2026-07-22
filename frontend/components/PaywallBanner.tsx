"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";

export function PaywallBanner({
  note,
  title = "You're viewing a preview",
}: {
  note?: string | null;
  title?: string;
}) {
  const pathname = usePathname();
  const { data: session } = useSession();
  const pricingHref = `/pricing?next=${encodeURIComponent(pathname || "/")}`;
  const ctaHref = session ? pricingHref : `/login?next=${encodeURIComponent(pricingHref)}`;
  const ctaLabel = session ? "Unlock with Pro" : "Sign in to unlock Pro";

  return (
    <div className="mb-6 rounded-xl border border-[var(--color-accent)]/35 bg-gradient-to-r from-[var(--color-accent)]/15 to-[var(--color-panel)] px-4 py-3.5 flex flex-col sm:flex-row sm:items-center gap-3 justify-between">
      <div className="min-w-0">
        <div className="text-sm font-semibold tracking-tight">{title}</div>
        <p className="text-sm text-[var(--color-muted)] mt-0.5">
          {note ||
            "Real data, trimmed for guests. Subscribe to open the full feed."}
        </p>
      </div>
      <Link
        href={ctaHref}
        className="shrink-0 inline-flex items-center justify-center rounded-lg bg-[var(--color-accent)] text-white text-sm font-medium px-4 py-2 hover:opacity-90"
      >
        {ctaLabel}
      </Link>
    </div>
  );
}

/** Soft lock strip at the bottom of a preview section. */
export function PaywallFade({ label = "Unlock the rest with Pro" }: { label?: string }) {
  const pathname = usePathname();
  const { data: session } = useSession();
  const pricingHref = `/pricing?next=${encodeURIComponent(pathname || "/")}`;
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
