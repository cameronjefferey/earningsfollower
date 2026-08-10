import { NextResponse } from "next/server";
import type { NextRequest, NextFetchEvent } from "next/server";
import { auth } from "@/auth";

const ADMIN_PREFIXES = ["/paper", "/learning", "/admin"];

// Auth.js is configured for the www host (AUTH_URL). Google redirects the OAuth
// callback there, so the PKCE/state cookie must also be set there. If sign-in
// starts on a different host (bare apex, or the Render default
// *.onrender.com hostname), the cookie is host-only to that host and missing
// at the www callback → "InvalidCheck: pkceCodeVerifier could not be parsed".
// Canonicalize every alias → www, including /api/auth.
const CANONICAL_HOST = "www.earningsfollower.com";
const ALIAS_HOSTS = new Set([
  "earningsfollower.com",
  "earningsfollower-web.onrender.com",
]);

function isPrefixed(path: string, prefixes: string[]): boolean {
  return prefixes.some((p) => path === p || path.startsWith(`${p}/`));
}

// Page-level gating (admin surfaces + legacy root redirects). Wrapped in auth()
// so req.auth is populated. Only invoked for non-apex, non-/api requests.
const gated = auth((req) => {
  const path = req.nextUrl.pathname;
  const request = req as unknown as NextRequest;

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

export default function middleware(req: NextRequest, event: NextFetchEvent) {
  // Canonicalize alias hosts → www before anything else, for EVERY path
  // including /api/auth, so the OAuth handshake lives entirely on one host.
  // 308 preserves method + body + query.
  const host = req.headers.get("host")?.split(":")[0]?.toLowerCase();
  if (host && ALIAS_HOSTS.has(host)) {
    const dest = new URL(req.url);
    dest.protocol = "https:";
    dest.hostname = CANONICAL_HOST;
    dest.port = "";
    return NextResponse.redirect(dest, 308);
  }

  // Never run the auth session wrapper on NextAuth's own endpoints (or any API
  // route) - just let them through. Alias hosts already redirected above.
  if (req.nextUrl.pathname.startsWith("/api")) {
    return NextResponse.next();
  }

  return (gated as unknown as (
    r: NextRequest,
    e: NextFetchEvent
  ) => ReturnType<typeof gated>)(req, event);
}

export const config = {
  // Run on all app routes AND /api (so apex→www canonicalization always applies,
  // including to the OAuth endpoints) except Next internals and static files.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|opengraph-image|twitter-image|llms.txt|marketing/).*)",
  ],
};
