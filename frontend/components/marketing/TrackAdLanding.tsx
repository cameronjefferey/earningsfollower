"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { reportTraffic } from "@/lib/ad-traffic";
import { captureAdAttrsFromSearch, readAdAttrs } from "@/lib/utm";

const ENGAGE_MS = 4000;

/**
 * Logs Reddit/ad landings + a soft engagement signal (4s visible or first
 * interaction). Persists via /api/ops/traffic; Telegram only for bot-ish landings.
 */
export function TrackAdLanding() {
  const pathname = usePathname();
  const params = useSearchParams();
  const landed = useRef(false);
  const engaged = useRef(false);
  const startedAt = useRef<number>(Date.now());

  useEffect(() => {
    const qs = params?.toString() ?? "";
    captureAdAttrsFromSearch(qs);
    if (landed.current) return;
    landed.current = true;
    startedAt.current = Date.now();

    const sp = new URLSearchParams(qs.startsWith("?") ? qs : `?${qs}`);
    const attrs = readAdAttrs();
    const rdt =
      sp.get("rdt_cid")?.trim() ||
      attrs.rdt_cid ||
      undefined;

    reportTraffic({
      kind: "ad_landing",
      path: pathname || "/start",
      rdt_cid: rdt,
      utm_source: sp.get("utm_source") || attrs.utm_source,
      utm_medium: sp.get("utm_medium") || attrs.utm_medium,
      utm_campaign: sp.get("utm_campaign") || attrs.utm_campaign,
    });

    const markEngage = () => {
      if (engaged.current) return;
      engaged.current = true;
      cleanup();
      reportTraffic({
        kind: "ad_engage",
        path: pathname || "/start",
        rdt_cid: rdt,
        utm_source: sp.get("utm_source") || attrs.utm_source,
        utm_medium: sp.get("utm_medium") || attrs.utm_medium,
        utm_campaign: sp.get("utm_campaign") || attrs.utm_campaign,
        engaged_ms: Math.max(0, Date.now() - startedAt.current),
      });
    };

    const onVis = () => {
      if (document.visibilityState === "hidden") return;
      if (Date.now() - startedAt.current >= ENGAGE_MS) markEngage();
    };

    const timer = window.setTimeout(markEngage, ENGAGE_MS);
    const opts: AddEventListenerOptions = { once: true, passive: true };
    window.addEventListener("pointerdown", markEngage, opts);
    window.addEventListener("keydown", markEngage, opts);
    window.addEventListener("scroll", markEngage, opts);
    document.addEventListener("visibilitychange", onVis);

    function cleanup() {
      window.clearTimeout(timer);
      window.removeEventListener("pointerdown", markEngage);
      window.removeEventListener("keydown", markEngage);
      window.removeEventListener("scroll", markEngage);
      document.removeEventListener("visibilitychange", onVis);
    }

    return cleanup;
  }, [pathname, params]);

  return null;
}
