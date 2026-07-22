import { NextResponse } from "next/server";
import { auth } from "@/auth";

const ADMIN_PREFIXES = ["/paper", "/learning"];

function isPrefixed(path: string, prefixes: string[]): boolean {
  return prefixes.some((p) => path === p || path.startsWith(`${p}/`));
}

export default auth((req) => {
  const path = req.nextUrl.pathname;

  // Admin surfaces stay hard-gated. Paid research pages are soft-gated in the
  // API/UI so guests can browse previews.
  if (isPrefixed(path, ADMIN_PREFIXES)) {
    if (!req.auth) {
      const login = new URL("/login", req.nextUrl.origin);
      login.searchParams.set("next", path);
      return NextResponse.redirect(login);
    }
    if (!req.auth.isAdmin) {
      return NextResponse.redirect(new URL("/", req.nextUrl.origin));
    }
  }

  return NextResponse.next();
});

export const config = {
  matcher: [
    "/paper/:path*",
    "/learning/:path*",
  ],
};
