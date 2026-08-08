/** Client-side mirror of backend bot_signals heuristics (for local tagging). */

export function scoreBot(userAgent: string | null | undefined): {
  score: number;
  reasons: string[];
} {
  const ua = (userAgent || "").trim();
  const reasons: string[] = [];
  let score = 0;

  if (!ua) {
    score += 70;
    reasons.push("empty_ua");
  } else if (/^mozilla\/5\.0\s*\(compatible\)\s*$/i.test(ua)) {
    score += 85;
    reasons.push("generic_ua");
  } else if (
    /(bot|crawl|spider|slurp|bytespider|facebookexternalhit|preview|headless|phantomjs|selenium|python-requests|curl\/|wget\/)/i.test(
      ua
    )
  ) {
    score += 75;
    reasons.push("ua_keyword");
  }

  if (
    ua.toLowerCase().startsWith("mozilla/5.0 (compatible") &&
    !ua.toLowerCase().includes("msie") &&
    !reasons.includes("generic_ua")
  ) {
    score = Math.max(score, 80);
    reasons.push("compatible_ua");
  }

  return { score: Math.min(100, score), reasons };
}

export function isBotSuspect(score: number): boolean {
  return score >= 50;
}
