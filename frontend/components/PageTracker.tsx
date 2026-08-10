"use client";

import { useSession } from "next-auth/react";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";
import { reportTraffic } from "@/lib/ad-traffic";
import { readAdAttrs } from "@/lib/utm";

/**
 * Site-wide behavior tracking: one pageview beacon per route change so we can
 * see what visitors actually use and explore. Skips admins (that's us) and
 * admin pages; waits for the session to settle so admin visits never log.
 */
function PageTrackerInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { data: session, status } = useSession();
  const lastPath = useRef<string | null>(null);
  const sentReferrer = useRef(false);

  useEffect(() => {
    if (status === "loading") return;
    if (session?.isAdmin) return;
    if (!pathname || pathname.startsWith("/admin")) return;
    if (lastPath.current === pathname) return;
    lastPath.current = pathname;

    const viewer =
      status !== "authenticated"
        ? "guest"
        : session?.subscribed
          ? "pro"
          : "member";
    // Only the first pageview of a session carries the external referrer.
    let referrer: string | undefined;
    if (!sentReferrer.current) {
      sentReferrer.current = true;
      const ref = typeof document !== "undefined" ? document.referrer : "";
      if (ref && !ref.includes(window.location.hostname)) referrer = ref;
    }
    const attrs = readAdAttrs();
    reportTraffic({
      kind: "pageview",
      path: pathname,
      viewer,
      referrer,
      rdt_cid: attrs.rdt_cid,
      utm_source: attrs.utm_source,
      utm_campaign: attrs.utm_campaign,
    });
    // searchParams is intentionally unused: we log route changes, not query noise.
  }, [pathname, searchParams, status, session?.isAdmin, session?.subscribed]);

  return null;
}

export function PageTracker() {
  return (
    <Suspense fallback={null}>
      <PageTrackerInner />
    </Suspense>
  );
}
