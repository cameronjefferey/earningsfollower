"use client";

import { SessionProvider } from "next-auth/react";

export function Providers({ children }: { children: React.ReactNode }) {
  // Avoid background session polling — it was hammering /api/auth/session and
  // helping tip the Next.js dev server into an OOM restart loop locally.
  return (
    <SessionProvider refetchInterval={0} refetchOnWindowFocus={false}>
      {children}
    </SessionProvider>
  );
}
