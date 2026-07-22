import { NextResponse } from "next/server";
import { auth } from "@/auth";

const PAID_PREFIXES = [
  "/waves",
  "/drift",
  "/reddit",
  "/paper",
  "/learning",
  "/company",
];

const ADMIN_PREFIXES = ["/paper", "/learning"];

function isPrefixed(path: string, prefixes: string[]): boolean {
  return prefixes.some((p) => path === p || path.startsWith(`${p}/`));
}

export default auth((req) => {
  const path = req.nextUrl.pathname;

  // Admin surfaces are always gated (even when the paywall is off).
  if (isPrefixed(path, ADMIN_PREFIXES)) {
    if (!req.auth) {
      const login = new URL("/login", req.nextUrl.origin);
      login.searchParams.set("next", path);
      return NextResponse.redirect(login);
    }
    if (!req.auth.isAdmin) {
      return NextResponse.redirect(new URL("/", req.nextUrl.origin));
    }
    return NextResponse.next();
  }

  if (process.env.NEXT_PUBLIC_PAYWALL_ENABLED !== "true") {
    return NextResponse.next();
  }

  if (!isPrefixed(path, PAID_PREFIXES)) {
    return NextResponse.next();
  }

  if (!req.auth) {
    const login = new URL("/login", req.nextUrl.origin);
    login.searchParams.set("next", path);
    return NextResponse.redirect(login);
  }

  if (!req.auth.subscribed) {
    const pricing = new URL("/pricing", req.nextUrl.origin);
    pricing.searchParams.set("next", path);
    return NextResponse.redirect(pricing);
  }

  return NextResponse.next();
});

export const config = {
  matcher: [
    "/waves/:path*",
    "/drift/:path*",
    "/reddit/:path*",
    "/paper/:path*",
    "/learning/:path*",
    "/company/:path*",
  ],
};
