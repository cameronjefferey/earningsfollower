/** Persist ad UTMs from the landing URL and append them to signup destinations. */

const UTM_KEYS = [
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_content",
  "utm_term",
  "gclid",
  "fbclid",
  "ttclid",
  "rdt_cid",
] as const;

const STORAGE_KEY = "ef_ad_attrs";

export type AdAttrs = Partial<Record<(typeof UTM_KEYS)[number], string>>;

export function captureAdAttrsFromSearch(search: string): AdAttrs {
  if (typeof window === "undefined") return {};
  const params = new URLSearchParams(search.startsWith("?") ? search : `?${search}`);
  const attrs: AdAttrs = {};
  for (const key of UTM_KEYS) {
    const v = params.get(key)?.trim();
    if (v) attrs[key] = v.slice(0, 200);
  }
  if (Object.keys(attrs).length) {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(attrs));
    } catch {
      /* ignore quota / private mode */
    }
  }
  return attrs;
}

export function readAdAttrs(): AdAttrs {
  if (typeof window === "undefined") return {};
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as AdAttrs;
  } catch {
    return {};
  }
}

/** Append stored UTMs to a path (keeps existing query). */
export function withAdAttrs(path: string): string {
  const attrs = readAdAttrs();
  const keys = Object.keys(attrs) as Array<keyof AdAttrs>;
  if (!keys.length) return path;
  const url = new URL(path, "https://www.earningsfollower.com");
  for (const key of keys) {
    const v = attrs[key];
    if (v && !url.searchParams.has(key)) url.searchParams.set(key, v);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}
