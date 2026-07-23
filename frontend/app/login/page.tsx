"use client";

import { signIn, useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { Card } from "@/components/ui";

function LoginInner() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";

  useEffect(() => {
    if (status === "authenticated" && session) {
      if (session.subscribed) {
        router.replace(next);
        return;
      }
      // Keep the original destination so checkout can send them back.
      const pricing = `/pricing?next=${encodeURIComponent(next)}`;
      router.replace(pricing);
    }
  }, [status, session, router, next]);

  return (
    <div className="max-w-md mx-auto mt-10">
      <Card className="p-6 space-y-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Sign in</h1>
          <p className="text-sm text-[var(--color-muted)] mt-1">
            Use Google to access paid features. Calendar stays free.
          </p>
        </div>
        <button
          type="button"
          onClick={() => signIn("google", { callbackUrl: next })}
          className="w-full rounded-lg bg-[var(--color-accent)] text-white font-medium py-2.5 hover:opacity-90"
        >
          Continue with Google
        </button>
        <p className="text-xs text-[var(--color-muted)]">
          Free Google OAuth — no Auth.js / Clerk bill. Stripe only charges when
          someone subscribes.
        </p>
      </Card>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="text-sm text-[var(--color-muted)] mt-10 text-center">
          Loading…
        </div>
      }
    >
      <LoginInner />
    </Suspense>
  );
}
