import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";

const ADMIN_PREFIXES = ["/paper", "/learning"];

function isPrefixed(path: string, prefixes: string[]): boolean {
  return prefixes.some((p) => path === p || path.startsWith(`${p}/`));
}

export default auth((req) => {
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

export const config = {
  matcher: ["/", "/paper/:path*", "/learning/:path*"],
};
