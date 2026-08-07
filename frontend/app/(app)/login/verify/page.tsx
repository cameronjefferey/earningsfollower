"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Card } from "@/components/ui";
import { verifyEmailToken } from "@/lib/authApi";

function VerifyInner() {
  const params = useSearchParams();
  const token = params.get("token") || "";
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    if (!token) {
      setError("This verification link is missing a token.");
      return;
    }

    void (async () => {
      const res = await verifyEmailToken(token);
      if (!res.ok) {
        setError(res.error);
        return;
      }
      setDone(true);
    })();
  }, [token]);

  return (
    <div className="max-w-md mx-auto mt-10">
      <Card className="p-6 space-y-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Verify email</h1>
          <p className="text-sm text-[var(--color-muted)] mt-1">
            {done
              ? "Your email is verified. You can sign in anytime."
              : error
                ? "We couldn’t verify this link."
                : "Confirming your email…"}
          </p>
        </div>
        {error ? <p className="text-sm text-[var(--color-down)]">{error}</p> : null}
        {done ? (
          <p className="text-sm text-[var(--color-up)]">Email verified.</p>
        ) : null}
        <Link
          href="/login"
          className="inline-block text-sm text-[var(--color-accent)] hover:underline"
        >
          Continue to sign in
        </Link>
      </Card>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense
      fallback={
        <div className="text-sm text-[var(--color-muted)] mt-10 text-center">
          Loading…
        </div>
      }
    >
      <VerifyInner />
    </Suspense>
  );
}
