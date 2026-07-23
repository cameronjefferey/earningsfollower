import { API_BASE } from "@/lib/api";

export async function postBilling(
  path: string,
  accessToken: string | undefined,
  body: Record<string, string> = {}
): Promise<{ url?: string; detail?: string }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(
      `Could not reach API at ${API_BASE}. Check NEXT_PUBLIC_API_BASE / that the backend is up.`
    );
  }
  const data = (await res.json().catch(() => ({}))) as {
    url?: string;
    detail?: string | { msg?: string }[];
  };
  if (!res.ok) {
    const detail = data.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg).filter(Boolean).join("; ")
          : `Request failed (${res.status})`;
    throw new Error(message || `Request failed (${res.status})`);
  }
  return data;
}
