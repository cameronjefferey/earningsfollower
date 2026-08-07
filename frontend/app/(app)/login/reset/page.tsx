"use client";

import Link from "next/link";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { Card } from "@/components/ui";
import { resetPassword } from "@/lib/authApi";

function ResetInner() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!token) {
      setError("Missing reset token. Request a new link.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const res = await resetPassword(token, password);
      if (!res.ok) {
        setError(res.error);
        return;
      }
      const result = await signIn("credentials", {
        email: res.data.email,
        password,
        redirect: false,
        callbackUrl: "/",
      });
      if (result?.error) {
        router.replace("/login");
        return;
      }
      router.replace(result?.url || "/");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-md mx-auto mt-10">
      <Card className="p-6 space-y-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Choose a new password</h1>
          <p className="text-sm text-[var(--color-muted)] mt-1">
            At least 8 characters. You&apos;ll be signed in afterward.
          </p>
        </div>
        {!token ? (
          <p className="text-sm text-[var(--color-down)]">
            This reset link is missing a token.{" "}
            <Link href="/login/forgot" className="underline">
              Request a new one
            </Link>
            .
          </p>
        ) : (
          <form onSubmit={onSubmit} className="space-y-3">
            <label className="block space-y-1">
              <span className="text-xs text-[var(--color-muted)]">New password</span>
              <input
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2 text-sm outline-none focus:border-[var(--color-accent)]"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs text-[var(--color-muted)]">Confirm password</span>
              <input
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="w-full rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2 text-sm outline-none focus:border-[var(--color-accent)]"
              />
            </label>
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg bg-[var(--color-accent)] text-white font-medium py-2.5 hover:opacity-90 disabled:opacity-60"
            >
              {busy ? "Saving…" : "Update password"}
            </button>
          </form>
        )}
        {error ? <p className="text-sm text-[var(--color-down)]">{error}</p> : null}
        <Link
          href="/login"
          className="block text-sm text-[var(--color-muted)] hover:text-white"
        >
          ← Back to sign in
        </Link>
      </Card>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <div className="text-sm text-[var(--color-muted)] mt-10 text-center">
          Loading…
        </div>
      }
    >
      <ResetInner />
    </Suspense>
  );
}
