"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuthReady } from "@/lib/useAuthReady";
import { FREE_COMPANY_LIMIT } from "@/lib/companyMeter";

const MEMBER_KEY = "ef.calendar.welcome.v1";
const GUEST_KEY = "ef.calendar.guest.v1";

/**
 * First-run strip on the calendar.
 * Guests: nudge into company pages (the free taste) + free account.
 * Free signed-in: confirm what's free and where Pro starts.
 * Pro: nothing. Dismiss persists per-variant in localStorage.
 */
export function CalendarWelcome() {
  const { ready, status, subscribed } = useAuthReady();
  const [variant, setVariant] = useState<"guest" | "member" | null>(null);

  useEffect(() => {
    if (!ready || subscribed) {
      setVariant(null);
      return;
    }
    const next = status === "authenticated" ? "member" : "guest";
    const key = next === "member" ? MEMBER_KEY : GUEST_KEY;
    try {
      if (localStorage.getItem(key)) {
        setVariant(null);
        return;
      }
    } catch {
      /* private mode - still show once this session */
    }
    setVariant(next);
  }, [ready, status, subscribed]);

  function dismiss() {
    try {
      localStorage.setItem(variant === "member" ? MEMBER_KEY : GUEST_KEY, "1");
    } catch {
      /* ignore */
    }
    setVariant(null);
  }

  if (!variant) return null;

  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-lg border border-[var(--color-edge)]/60 bg-[var(--color-panel)]/40 px-3 py-2">
      {variant === "guest" ? (
        <p className="min-w-0 text-sm text-[var(--color-muted)]">
          <span className="font-medium text-white">Free calendar, no account needed.</span>{" "}
          Open any name for its full earnings history ({FREE_COMPANY_LIMIT} company
          pages free as a guest).
        </p>
      ) : (
        <p className="min-w-0 text-sm text-[var(--color-muted)]">
          <span className="font-medium text-white">You&apos;re in.</span>{" "}
          Calendar and company pages are free. Pro unlocks the live Waves &amp; Drift
          boards.
        </p>
      )}
      <div className="flex shrink-0 items-center gap-3">
        {variant === "guest" ? (
          <Link
            href="/login?mode=signup&next=/calendar"
            className="text-sm text-[var(--color-accent)] hover:underline"
          >
            Free account = unlimited
          </Link>
        ) : (
          <Link
            href="/boards"
            onClick={dismiss}
            className="text-sm text-[var(--color-accent)] hover:underline"
          >
            Preview boards
          </Link>
        )}
        <button
          type="button"
          onClick={dismiss}
          className="text-sm text-[var(--color-muted)] hover:text-white"
          aria-label="Dismiss welcome"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
