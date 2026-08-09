"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { reportFunnel } from "@/lib/ad-traffic";
import { useAuthReady } from "@/lib/useAuthReady";
import { captureAdAttrsFromSearch, readAdAttrs } from "@/lib/utm";

/**
 * Funnel beacon: guests and ad-attributed visitors reaching the calendar.
 * Signed-in members without ad attribution are skipped so normal daily use
 * doesn't drown the funnel numbers. Once per browser session.
 */
function TrackCalendarViewInner() {
  const { ready, status } = useAuthReady();
  const params = useSearchParams();

  useEffect(() => {
    if (!ready) return;
    // Direct ad deep-links to /calendar carry UTMs; persist them like /start does.
    captureAdAttrsFromSearch(params?.toString() ?? "");
    const attrs = readAdAttrs();
    const attributed = Boolean(attrs.rdt_cid || attrs.utm_source);
    if (status === "authenticated" && !attributed) return;
    reportFunnel("calendar_view", { path: "/calendar", once: "calendar" });
  }, [ready, status, params]);

  return null;
}

export function TrackCalendarView() {
  return (
    <Suspense fallback={null}>
      <TrackCalendarViewInner />
    </Suspense>
  );
}
