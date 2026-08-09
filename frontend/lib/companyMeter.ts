/**
 * Guest meter for company pages: a few free deep-dives per browser, then a
 * signup gate. Signed-in users are never metered. localStorage-based — easy to
 * bypass on purpose; this is a nudge for real visitors, not DRM.
 */

const KEY = "ef.company.viewed.v1";

export const FREE_COMPANY_LIMIT = 3;

function readViewed(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((t): t is string => typeof t === "string");
  } catch {
    return [];
  }
}

/**
 * Record a guest view of `ticker`. Revisiting an already-counted ticker never
 * burns quota. Returns whether the page may render and how many new companies
 * the guest can still open. `remaining` is null when storage is unavailable
 * (private mode) — in that case we always allow rather than lock someone out.
 */
export function recordCompanyView(ticker: string): {
  allowed: boolean;
  remaining: number | null;
} {
  const t = ticker.trim().toUpperCase();
  if (!t) return { allowed: true, remaining: null };
  try {
    const viewed = readViewed();
    if (viewed.includes(t)) {
      return { allowed: true, remaining: Math.max(0, FREE_COMPANY_LIMIT - viewed.length) };
    }
    if (viewed.length >= FREE_COMPANY_LIMIT) {
      return { allowed: false, remaining: 0 };
    }
    viewed.push(t);
    localStorage.setItem(KEY, JSON.stringify(viewed));
    return { allowed: true, remaining: FREE_COMPANY_LIMIT - viewed.length };
  } catch {
    return { allowed: true, remaining: null };
  }
}
