"use client";

import Link from "next/link";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Card } from "@/components/ui";

function MagicInner() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") || "";
  const next = params.get("next") || "/";
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    if (!token) {
      setError("This sign-in link is missing a token.");
      return;
    }

    void (async () => {
      const result = await signIn("credentials", {
        magicToken: token,
        redirect: false,
        callbackUrl: next,
      });
      if (result?.error) {
        setError("This sign-in link is invalid or has expired.");
        return;
      }
      router.replace(result?.url || next);
    })();
  }, [token, next, router]);

  return (
    <div className="max-w-md mx-auto mt-10">
      <Card className="p-6 space-y-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Signing you in</h1>
          <p className="text-sm text-[var(--color-muted)] mt-1">
            {error ? "Something went wrong with this link." : "One moment…"}
          </p>
        </div>
        {error ? (
          <>
            <p className="text-sm text-[var(--color-down)]">{error}</p>
            <Link
              href="/login"
              className="inline-block text-sm text-[var(--color-accent)] hover:underline"
            >
              Request a new magic link
            </Link>
          </>
        ) : null}
      </Card>
    </div>
  );
}

export default function MagicLoginPage() {
  return (
    <Suspense
      fallback={
        <div className="text-sm text-[var(--color-muted)] mt-10 text-center">
          Loading…
        </div>
      }
    >
      <MagicInner />
    </Suspense>
  );
}
