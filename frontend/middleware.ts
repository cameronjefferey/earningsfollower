import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";

const ADMIN_PREFIXES = ["/paper", "/learning"];

// Auth.js is configured for the www host (AUTH_URL). Google redirects the OAuth
// callback there, so the PKCE/state cookie must also be set there. If a user
// starts on the bare apex, the cookie is host-only to the apex and is missing at
// the www callback → "InvalidCheck: pkceCodeVerifier could not be parsed". Keep
// the whole app (and therefore the sign-in flow) on one canonical host.
const APEX_HOST = "earningsfollower.com";
const CANONICAL_HOST = "www.earningsfollower.com";

function isPrefixed(path: string, prefixes: string[]): boolean {
  return prefixes.some((p) => path === p || path.startsWith(`${p}/`));
}

export default auth((req) => {
  const path = req.nextUrl.pathname;
  const request = req as unknown as NextRequest;

  // Canonicalize apex → www before anything else (SEO + keeps OAuth on one host).
  const host = req.headers.get("host")?.split(":")[0]?.toLowerCase();
  if (host === APEX_HOST) {
    const dest = new URL(req.url);
    dest.protocol = "https:";
    dest.hostname = CANONICAL_HOST;
    dest.port = "";
    return NextResponse.redirect(dest, 308);
  }

  // Old calendar lived at /. Preserve HappyTrader / deep links that still
  // pass tab or theme query params on the root URL.
  if (path === "/") {
    const tab = request.nextUrl.searchParams.get("tab");
    const theme = request.nextUrl.searchParams.get("theme");
    if (tab || theme) {
      const dest = new URL("/calendar", request.nextUrl.origin);
      request.nextUrl.searchParams.forEach((value, key) => {
        dest.searchParams.set(key, value);
      });
      return NextResponse.redirect(dest);
    }
  }

  // Admin surfaces stay hard-gated. Paid research pages are soft-gated in the
  // API/UI so guests can browse previews.
  if (isPrefixed(path, ADMIN_PREFIXES)) {
    if (!req.auth) {
      const login = new URL("/login", request.nextUrl.origin);
      login.searchParams.set("next", path);
      return NextResponse.redirect(login);
    }
    if (!req.auth.isAdmin) {
      return NextResponse.redirect(new URL("/calendar", request.nextUrl.origin));
    }
  }

  return NextResponse.next();
});

export const config = {
  // Run on all app routes (so apex→www canonicalization always applies) except
  // Next internals, the auth/API handlers, and static files.
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|opengraph-image|twitter-image|llms.txt|marketing/).*)",
  ],
};
