"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { withAdAttrs } from "@/lib/utm";

/**
 * CTA pair for the ad landing page. Hrefs pick up stored UTMs after mount so
 * attribution survives the click without a server/client hydration mismatch.
 */
export function AdCtas() {
  const [calendarHref, setCalendarHref] = useState("/calendar");
  const [signupHref, setSignupHref] = useState("/login?mode=signup&next=/calendar");

  useEffect(() => {
    setCalendarHref(withAdAttrs("/calendar"));
    setSignupHref(withAdAttrs("/login?mode=signup&next=/calendar"));
  }, []);

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Link href={calendarHref} className="m-btn-primary">
        Browse the free calendar →
      </Link>
      <Link href={signupHref} className="m-btn-ghost">
        Create free account
      </Link>
    </div>
  );
}
