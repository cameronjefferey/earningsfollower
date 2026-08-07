"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { Card } from "@/components/ui";
import { requestPasswordReset } from "@/lib/authApi";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNote(null);
    setBusy(true);
    try {
      const res = await requestPasswordReset(email.trim());
      if (!res.ok) {
        setError(res.error);
        return;
      }
      setNote(res.data.message || "Check your inbox for a reset link.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-md mx-auto mt-10">
      <Card className="p-6 space-y-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Reset password</h1>
          <p className="text-sm text-[var(--color-muted)] mt-1">
            We&apos;ll email a link to choose a new password.
          </p>
        </div>
        <form onSubmit={onSubmit} className="space-y-3">
          <label className="block space-y-1">
            <span className="text-xs text-[var(--color-muted)]">Email</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2 text-sm outline-none focus:border-[var(--color-accent)]"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-[var(--color-accent)] text-white font-medium py-2.5 hover:opacity-90 disabled:opacity-60"
          >
            {busy ? "Sending…" : "Send reset link"}
          </button>
        </form>
        {error ? <p className="text-sm text-[var(--color-down)]">{error}</p> : null}
        {note ? <p className="text-sm text-[var(--color-up)]">{note}</p> : null}
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
