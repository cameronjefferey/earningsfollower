"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { reportFunnel } from "@/lib/ad-traffic";
import { withAdAttrs } from "@/lib/utm";

/**
 * CTA pair for the ad landing page. Hrefs pick up stored UTMs after mount so
 * attribution survives the click without a server/client hydration mismatch.
 * `placement` tags the funnel beacon so we can compare hero vs mid vs bottom.
 */
export function AdCtas({
  placement = "hero",
  primary = "signup",
}: {
  placement?: string;
  /** Which action gets the filled button. */
  primary?: "signup" | "browse";
}) {
  const [calendarHref, setCalendarHref] = useState("/calendar");
  const [signupHref, setSignupHref] = useState("/login?mode=signup&next=/calendar");

  useEffect(() => {
    setCalendarHref(withAdAttrs("/calendar"));
    setSignupHref(withAdAttrs("/login?mode=signup&next=/calendar"));
  }, []);

  const signup = (
    <Link
      key="signup"
      href={signupHref}
      className={primary === "signup" ? "m-btn-primary" : "m-btn-ghost"}
      onClick={() =>
        reportFunnel("cta_click", {
          path: "/start",
          target: `create_account_${placement}`,
        })
      }
    >
      Create free account
    </Link>
  );
  const browse = (
    <Link
      key="browse"
      href={calendarHref}
      className={primary === "browse" ? "m-btn-primary" : "m-btn-ghost"}
      onClick={() =>
        reportFunnel("cta_click", {
          path: "/start",
          target: `browse_calendar_${placement}`,
        })
      }
    >
      Browse the free calendar →
    </Link>
  );

  return (
    <div className="flex flex-wrap items-center gap-3">
      {primary === "browse" ? [browse, signup] : [signup, browse]}
    </div>
  );
}
