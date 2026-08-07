/**
 * Reddit Ads Pixel helpers.
 * Set NEXT_PUBLIC_REDDIT_PIXEL_ID from Ads Manager → Events Manager.
 */

export const REDDIT_PIXEL_ID =
  typeof process !== "undefined"
    ? (process.env.NEXT_PUBLIC_REDDIT_PIXEL_ID || "").trim()
    : "";

export type RedditTrackEvent =
  | "PageVisit"
  | "ViewContent"
  | "Search"
  | "AddToCart"
  | "AddToWishlist"
  | "Purchase"
  | "Lead"
  | "SignUp"
  | "Custom";

type RedditPayload = Record<string, string | number | boolean | undefined | null>;

declare global {
  interface Window {
    rdt?: (...args: unknown[]) => void;
  }
}

export function isRedditPixelEnabled(): boolean {
  return Boolean(REDDIT_PIXEL_ID);
}

export function trackReddit(
  event: RedditTrackEvent,
  payload?: RedditPayload
): void {
  if (typeof window === "undefined" || !REDDIT_PIXEL_ID) return;
  try {
    if (typeof window.rdt !== "function") return;
    if (payload && Object.keys(payload).length > 0) {
      window.rdt("track", event, payload);
    } else {
      window.rdt("track", event);
    }
  } catch {
    /* never break the app for analytics */
  }
}

export function trackRedditSignUp(email?: string): void {
  trackReddit("SignUp", email ? { email: email.trim().toLowerCase() } : undefined);
}

export function trackRedditPurchase(input: {
  value?: number;
  currency?: string;
  conversionId?: string;
  email?: string;
}): void {
  trackReddit("Purchase", {
    value: input.value,
    currency: input.currency ?? "USD",
    conversionId: input.conversionId,
    email: input.email?.trim().toLowerCase(),
    itemCount: 1,
  });
}
