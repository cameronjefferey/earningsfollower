/** Fire-and-forget ad / auth traffic beacons via the Next.js ops proxy. */

import { readAdAttrs } from "@/lib/utm";

export type TrafficKind =
  | "ad_landing"
  | "ad_engage"
  | "auth_fail"
  | "cta_click"
  | "calendar_view"
  | "company_view"
  | "guest_gate"
  | "signup"
  | "pageview";

export type TrafficPayload = {
  kind: TrafficKind;
  path?: string;
  target?: string;
  sid?: string;
  referrer?: string;
  viewer?: string;
  rdt_cid?: string;
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  engaged_ms?: number;
  auth_error?: string;
  auth_cause?: string;
  message?: string;
};

/** Anonymous per-browser-session id so backend events stitch into journeys. */
export function getSessionId(): string | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const existing = sessionStorage.getItem("ef_sid");
    if (existing) return existing;
    const sid = Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    sessionStorage.setItem("ef_sid", sid);
    return sid;
  } catch {
    return undefined;
  }
}

/**
 * Log one step of the visitor funnel (CTA click, calendar/company view, gate,
 * signup). Attaches stored ad attribution automatically; `once` dedupes per
 * browser session so refreshes don't inflate counts.
 */
export function reportFunnel(
  kind: Exclude<TrafficKind, "ad_landing" | "ad_engage" | "auth_fail">,
  opts: { path?: string; target?: string; once?: string } = {}
): void {
  if (typeof window === "undefined") return;
  if (opts.once) {
    const key = `ef_funnel_${kind}_${opts.once}`;
    try {
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, "1");
    } catch {
      /* private mode — fire anyway */
    }
  }
  const attrs = readAdAttrs();
  reportTraffic({
    kind,
    path: opts.path,
    target: opts.target,
    rdt_cid: attrs.rdt_cid,
    utm_source: attrs.utm_source,
    utm_medium: attrs.utm_medium,
    utm_campaign: attrs.utm_campaign,
  });
}

/**
 * Signup beacon deduped per browser (localStorage, keyed by email) because the
 * session's trackSignUp flag lives in the JWT and can resurface across visits.
 */
export function reportSignupOnce(email: string | undefined, method: string): void {
  if (typeof window === "undefined") return;
  const key = email
    ? `ef_funnel_signup_${email.trim().toLowerCase()}`
    : "ef_funnel_signup";
  try {
    if (localStorage.getItem(key)) return;
    localStorage.setItem(key, "1");
  } catch {
    /* private mode — fire anyway */
  }
  reportFunnel("signup", { target: method });
}

export function reportTraffic(payload: TrafficPayload): void {
  if (typeof window === "undefined") return;
  try {
    if (!payload.sid) payload.sid = getSessionId();
    const body = JSON.stringify(payload);
    // prefer sendBeacon so unloads still flush engage events
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: "application/json" });
      if (navigator.sendBeacon("/api/ops/traffic", blob)) return;
    }
    void fetch("/api/ops/traffic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
      cache: "no-store",
    }).catch(() => {
      /* ignore */
    });
  } catch {
    /* ignore */
  }
}
