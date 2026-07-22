import { API_BASE } from "@/lib/api";

export async function postBilling(
  path: string,
  accessToken: string | undefined,
  body: Record<string, string> = {}
): Promise<{ url?: string; detail?: string }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as {
    url?: string;
    detail?: string;
  };
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(
      typeof detail === "string" ? detail : `Request failed (${res.status})`
    );
  }
  return data;
}
