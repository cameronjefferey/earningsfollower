"use client";

import Link from "next/link";
import { signIn, useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { Card } from "@/components/ui";
import { registerAccount, requestMagicLink } from "@/lib/authApi";
import { reportSignupOnce } from "@/lib/ad-traffic";
import { trackRedditSignUp } from "@/lib/reddit-pixel";

type Mode = "signin" | "signup";

function safeNextPath(raw: string | null): string {
  // Free users land on the calendar by default - never force Pricing after login.
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw === "/") {
    return "/calendar";
  }
  return raw;
}

function LoginInner() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const initialMode: Mode =
    params.get("mode") === "signup" ? "signup" : "signin";
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [magicBusy, setMagicBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (status === "authenticated" && session) {
      router.replace(next);
    }
  }, [status, session, router, next]);

  async function onPasswordSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNote(null);
    setBusy(true);
    try {
      if (mode === "signup") {
        const reg = await registerAccount({
          email: email.trim(),
          password,
          name: name.trim() || undefined,
        });
        if (!reg.ok) {
          setError(reg.error);
          return;
        }
        try {
          const key = `ef_rdt_signup_${email.trim().toLowerCase()}`;
          if (!sessionStorage.getItem(key)) {
            sessionStorage.setItem(key, "1");
            trackRedditSignUp(email.trim());
          }
        } catch {
          trackRedditSignUp(email.trim());
        }
        reportSignupOnce(email.trim(), "password");
        setNote(reg.data.message);
      }

      const result = await signIn("credentials", {
        email: email.trim(),
        password,
        redirect: false,
        callbackUrl: next,
      });
      if (result?.error) {
        setError(
          mode === "signup"
            ? "Account created, but sign-in failed. Try signing in."
            : "Invalid email or password."
        );
        return;
      }
      if (result?.url) {
        router.replace(result.url);
      }
    } finally {
      setBusy(false);
    }
  }

  async function onMagicLink() {
    setError(null);
    setNote(null);
    if (!email.trim()) {
      setError("Enter your email to receive a magic link.");
      return;
    }
    setMagicBusy(true);
    try {
      const res = await requestMagicLink(email.trim());
      if (!res.ok) {
        setError(res.error);
        return;
      }
      setNote(
        res.data.message ||
          `Check ${email.trim()} for a sign-in link (and Spam / Promotions).`
      );
    } finally {
      setMagicBusy(false);
    }
  }

  return (
    <div className="max-w-md mx-auto mt-10">
      <Card className="p-6 space-y-5">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {mode === "signin" ? "Sign in" : "Create account"}
          </h1>
          <p className="text-sm text-[var(--color-muted)] mt-1">
            Google, email & password, or a magic link. Calendar stays free.
          </p>
        </div>

        <div className="flex rounded-lg border border-[var(--color-edge)] p-0.5 text-sm">
          <button
            type="button"
            onClick={() => {
              setMode("signin");
              setError(null);
              setNote(null);
            }}
            className={`flex-1 rounded-md py-1.5 font-medium transition-colors ${
              mode === "signin"
                ? "bg-[var(--color-panel-2)] text-white"
                : "text-[var(--color-muted)] hover:text-white"
            }`}
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => {
              setMode("signup");
              setError(null);
              setNote(null);
            }}
            className={`flex-1 rounded-md py-1.5 font-medium transition-colors ${
              mode === "signup"
                ? "bg-[var(--color-panel-2)] text-white"
                : "text-[var(--color-muted)] hover:text-white"
            }`}
          >
            Create account
          </button>
        </div>

        <button
          type="button"
          onClick={() => signIn("google", { callbackUrl: next })}
          className="w-full rounded-lg bg-[var(--color-accent)] text-white font-medium py-2.5 hover:opacity-90"
        >
          Continue with Google
        </button>

        <div className="relative text-center">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-[var(--color-edge)]" />
          </div>
          <span className="relative bg-[var(--color-panel)] px-3 text-xs text-[var(--color-muted)]">
            or use email
          </span>
        </div>

        <form onSubmit={onPasswordSubmit} className="space-y-3">
          {mode === "signup" ? (
            <label className="block space-y-1">
              <span className="text-xs text-[var(--color-muted)]">Name (optional)</span>
              <input
                type="text"
                autoComplete="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2 text-sm outline-none focus:border-[var(--color-accent)]"
              />
            </label>
          ) : null}
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
          <label className="block space-y-1">
            <span className="text-xs text-[var(--color-muted)]">Password</span>
            <input
              type="password"
              required
              minLength={8}
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2 text-sm outline-none focus:border-[var(--color-accent)]"
            />
          </label>

          {mode === "signin" ? (
            <div className="text-right">
              <Link
                href="/login/forgot"
                className="text-xs text-[var(--color-muted)] hover:text-white"
              >
                Forgot password?
              </Link>
            </div>
          ) : null}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] font-medium py-2.5 text-sm hover:border-[var(--color-accent)]/60 disabled:opacity-60"
          >
            {busy
              ? "Working…"
              : mode === "signin"
                ? "Sign in with email"
                : "Create account"}
          </button>
        </form>

        <button
          type="button"
          onClick={onMagicLink}
          disabled={magicBusy}
          className="w-full text-sm text-[var(--color-muted)] hover:text-white disabled:opacity-60"
        >
          {magicBusy ? "Sending link…" : "Email me a magic link instead"}
        </button>

        {error ? (
          <p className="text-sm text-[var(--color-down)]">{error}</p>
        ) : null}
        {note ? (
          <p className="text-sm text-[var(--color-up)]">{note}</p>
        ) : null}
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
