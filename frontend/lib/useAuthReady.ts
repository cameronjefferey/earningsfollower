"use client";

import { useSession } from "next-auth/react";

/** True once Auth.js has settled — never treat "loading" as a logged-out guest. */
export function useAuthReady() {
  const { data: session, status } = useSession();
  return {
    ready: status !== "loading",
    status,
    session,
    accessToken: session?.accessToken as string | undefined,
    subscribed: Boolean(session?.subscribed || session?.isAdmin),
    isAdmin: Boolean(session?.isAdmin),
  };
}
