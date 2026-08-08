import { handlers } from "@/auth";
import { authRequestContext } from "@/lib/auth-request-context";

function withAuthContext(req: Request, run: () => Promise<Response>): Promise<Response> {
  const ua = req.headers.get("user-agent") || "";
  const forwarded = req.headers.get("x-forwarded-for") || "";
  const ip = forwarded.split(",")[0]?.trim() || "";
  let path = "/api/auth";
  try {
    path = new URL(req.url).pathname;
  } catch {
    /* ignore */
  }
  return authRequestContext.run({ ua, ip, path }, run);
}

export async function GET(req: Request) {
  return withAuthContext(req, () => handlers.GET(req));
}

export async function POST(req: Request) {
  return withAuthContext(req, () => handlers.POST(req));
}
