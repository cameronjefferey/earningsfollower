import { API_BASE } from "@/lib/api";

async function postAuth<T>(
  path: string,
  body: Record<string, unknown>
): Promise<{ ok: true; data: T } | { ok: false; error: string; status: number }> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = (await res.json().catch(() => ({}))) as T & { detail?: unknown };
    if (!res.ok) {
      const detail = data.detail;
      let error = `Request failed (${res.status})`;
      if (typeof detail === "string") error = detail;
      else if (Array.isArray(detail) && detail[0]?.msg) error = String(detail[0].msg);
      return { ok: false, error, status: res.status };
    }
    return { ok: true, data };
  } catch {
    return { ok: false, error: "Could not reach the server.", status: 0 };
  }
}

export function registerAccount(input: {
  email: string;
  password: string;
  name?: string;
}) {
  return postAuth<{
    ok: boolean;
    email: string;
    verify_email_sent: boolean;
    message: string;
  }>("/auth/register", input);
}

export function requestMagicLink(email: string) {
  return postAuth<{ ok: boolean; message: string }>("/auth/magic/request", {
    email,
  });
}

export function requestPasswordReset(email: string) {
  return postAuth<{ ok: boolean; message: string }>("/auth/password/forgot", {
    email,
  });
}

export function resetPassword(token: string, password: string) {
  return postAuth<{ ok: boolean; email: string }>("/auth/password/reset", {
    token,
    password,
  });
}

export function verifyEmailToken(token: string) {
  return postAuth<{ ok: boolean; email: string }>("/auth/email/verify", {
    token,
  });
}
