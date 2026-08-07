"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuthReady } from "@/lib/useAuthReady";

const STORAGE_KEY = "ef.calendar.welcome.v1";

/**
 * First-run strip for free signed-in users on the calendar.
 * Guests and Pro subscribers never see it; dismiss persists in localStorage.
 */
export function CalendarWelcome() {
  const { ready, status, subscribed } = useAuthReady();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!ready || status !== "authenticated" || subscribed) {
      setVisible(false);
      return;
    }
    try {
      if (localStorage.getItem(STORAGE_KEY)) {
        setVisible(false);
        return;
      }
    } catch {
      /* private mode — still show once this session */
    }
    setVisible(true);
  }, [ready, status, subscribed]);

  function dismiss() {
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      /* ignore */
    }
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-lg border border-[var(--color-edge)]/60 bg-[var(--color-panel)]/40 px-3 py-2">
      <p className="min-w-0 text-sm text-[var(--color-muted)]">
        <span className="font-medium text-white">You&apos;re in</span>
        {" — "}
        calendar is free. Pro unlocks Drift &amp; Waves when you&apos;re ready.
      </p>
      <div className="flex shrink-0 items-center gap-3">
        <Link
          href="/boards"
          onClick={dismiss}
          className="text-sm text-[var(--color-accent)] hover:underline"
        >
          Preview boards
        </Link>
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
