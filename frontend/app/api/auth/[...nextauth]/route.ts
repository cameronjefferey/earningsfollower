import type { NextRequest } from "next/server";
import { handlers } from "@/auth";
import { authRequestContext } from "@/lib/auth-request-context";

function withAuthContext(
  req: NextRequest,
  run: () => Promise<Response>
): Promise<Response> {
  const ua = req.headers.get("user-agent") || "";
  const forwarded = req.headers.get("x-forwarded-for") || "";
  const ip = forwarded.split(",")[0]?.trim() || "";
  let path = "/api/auth";
  try {
    path = req.nextUrl.pathname;
  } catch {
    /* ignore */
  }
  return authRequestContext.run({ ua, ip, path }, run);
}

export async function GET(req: NextRequest) {
  return withAuthContext(req, () => handlers.GET(req));
}

export async function POST(req: NextRequest) {
  return withAuthContext(req, () => handlers.POST(req));
}
