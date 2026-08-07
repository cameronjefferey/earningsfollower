"use client";

import Script from "next/script";
import { useSession } from "next-auth/react";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";
import {
  REDDIT_PIXEL_ID,
  isRedditPixelEnabled,
  trackReddit,
  trackRedditSignUp,
} from "@/lib/reddit-pixel";

/**
 * Loads the Reddit Pixel once and fires PageVisit on route changes.
 * Also fires SignUp when Auth.js reports a newly created account (Google / first upsert).
 */
function RedditPixelInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { data: session } = useSession();
  const lastPath = useRef<string | null>(null);
  const signedUp = useRef(false);

  useEffect(() => {
    if (!isRedditPixelEnabled()) return;
    const qs = searchParams?.toString();
    const key = qs ? `${pathname}?${qs}` : pathname;
    if (lastPath.current === key) return;
    lastPath.current = key;
    trackReddit("PageVisit");
  }, [pathname, searchParams]);

  useEffect(() => {
    if (!isRedditPixelEnabled() || signedUp.current) return;
    if (!session?.trackSignUp) return;
    const email = (session.user?.email || "").trim().toLowerCase();
    const dedupeKey = email ? `ef_rdt_signup_${email}` : "ef_rdt_signup";
    try {
      if (sessionStorage.getItem(dedupeKey)) {
        signedUp.current = true;
        return;
      }
      sessionStorage.setItem(dedupeKey, "1");
    } catch {
      /* private mode — still fire once this mount */
    }
    signedUp.current = true;
    trackRedditSignUp(email || undefined);
  }, [session?.trackSignUp, session?.user?.email]);

  if (!isRedditPixelEnabled()) return null;

  // PageVisit is fired from the route effect so SPA navigations are covered once.
  const init = `
!function(w,d){if(!w.rdt){var p=w.rdt=function(){p.sendEvent?p.sendEvent.apply(p,arguments):p.callQueue.push(arguments)};p.callQueue=[];var t=d.createElement("script");t.src="https://www.redditstatic.com/ads/pixel.js";t.async=!0;var s=d.getElementsByTagName("script")[0];s.parentNode.insertBefore(t,s)}}(window,document);
rdt('init','${REDDIT_PIXEL_ID}');
`;

  return (
    <Script id="reddit-pixel" strategy="afterInteractive">
      {init}
    </Script>
  );
}

export function RedditPixel() {
  if (!isRedditPixelEnabled()) return null;
  return (
    <Suspense fallback={null}>
      <RedditPixelInner />
    </Suspense>
  );
}
