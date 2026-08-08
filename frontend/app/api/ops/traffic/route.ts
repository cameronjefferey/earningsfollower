import { NextResponse } from "next/server";

/**
 * Browser → Next proxy → backend /ops/traffic.
 * Keeps AUTH_SECRET off the client while allowing ad-landing beacons.
 */
export async function POST(req: Request) {
  const secret = process.env.AUTH_SECRET;
  const apiBase =
    process.env.AUTH_API_BASE ||
    process.env.NEXT_PUBLIC_API_BASE ||
    "http://127.0.0.1:8000";

  if (!secret) {
    return NextResponse.json({ ok: false, error: "unconfigured" }, { status: 503 });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "bad_json" }, { status: 400 });
  }

  const ua = req.headers.get("user-agent") || undefined;
  const forwarded = req.headers.get("x-forwarded-for");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${secret}`,
  };
  if (ua) headers["User-Agent"] = ua;
  if (forwarded) headers["X-Forwarded-For"] = forwarded;

  try {
    const res = await fetch(`${apiBase.replace(/\/$/, "")}/ops/traffic`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        ...(typeof body === "object" && body ? body : {}),
        ua: ua || undefined,
      }),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({ ok: res.ok }));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ ok: false, error: "upstream" }, { status: 502 });
  }
}
