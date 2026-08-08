/** Fire-and-forget ad / auth traffic beacons via the Next.js ops proxy. */

export type TrafficKind = "ad_landing" | "ad_engage" | "auth_fail";

export type TrafficPayload = {
  kind: TrafficKind;
  path?: string;
  rdt_cid?: string;
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  engaged_ms?: number;
  auth_error?: string;
  auth_cause?: string;
  message?: string;
};

export function reportTraffic(payload: TrafficPayload): void {
  if (typeof window === "undefined") return;
  try {
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
