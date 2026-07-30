import { API_BASE } from "@/lib/api";

export type BillingResponse = {
  url?: string;
  id?: string;
  detail?: string;
  already_subscribed?: boolean;
  subscribed?: boolean;
  subscription_status?: string;
  synced?: boolean;
  current_period_end?: string | null;
  stripe_customer_id?: string | null;
  stripe_subscription_id?: string | null;
};

export async function postBilling(
  path: string,
  accessToken: string | undefined,
  body: Record<string, string> = {}
): Promise<BillingResponse> {
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
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) {
    const detail = data.detail;
    let message = `Request failed (${res.status})`;
    if (typeof detail === "string") {
      message = detail;
    } else if (Array.isArray(detail)) {
      message =
        detail
          .map((d) =>
            d && typeof d === "object" && "msg" in d
              ? String((d as { msg?: string }).msg || "")
              : ""
          )
          .filter(Boolean)
          .join("; ") || message;
    }
    throw new Error(message);
  }
  return data as BillingResponse;
}
