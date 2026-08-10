"use client";

import Link from "next/link";
import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { registerAccount, requestMagicLink } from "@/lib/authApi";
import { reportSignupOnce } from "@/lib/ad-traffic";
import { trackRedditSignUp } from "@/lib/reddit-pixel";
import { withAdAttrs } from "@/lib/utm";

/**
 * Signup-first panel for the ad landing page. After auth, sends people to the
 * free calendar (not hard-paywall Pricing) so the ad promise stays honest.
 */
export function AdSignupCard({ next = "/calendar" }: { next?: string }) {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [magicBusy, setMagicBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  function dest(): string {
    return withAdAttrs(next);
  }

  useEffect(() => {
    if (status === "authenticated" && session) {
      router.replace(withAdAttrs(next));
    }
  }, [status, session, router, next]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNote(null);
    setBusy(true);
    const callbackUrl = dest();
    try {
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
      const result = await signIn("credentials", {
        email: email.trim(),
        password,
        redirect: false,
        callbackUrl,
      });
      if (result?.error) {
        setError("Account created - sign in to continue.");
        return;
      }
      router.replace(result?.url || callbackUrl);
    } finally {
      setBusy(false);
    }
  }

  async function onMagic() {
    setError(null);
    setNote(null);
    if (!email.trim()) {
      setError("Enter your email for a magic link.");
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

  if (status === "authenticated") {
    return (
      <div className="m-ad-card">
        <p className="text-sm text-[var(--m-muted)]">Signed in - opening the calendar…</p>
      </div>
    );
  }

  return (
    <div className="m-ad-card">
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-white tracking-tight">
          Create your free account
        </h2>
        <p className="text-sm text-[var(--m-muted)] mt-1">
          Calendar stays free. Pro boards unlock when you&apos;re ready.
        </p>
      </div>

      <button
        type="button"
        onClick={() => signIn("google", { callbackUrl: dest() })}
        className="m-btn-primary w-full"
      >
        Continue with Google
      </button>

      <div className="relative text-center my-4">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-[var(--m-line)]" />
        </div>
        <span className="relative bg-[var(--m-bg-elev)] px-3 text-xs text-[var(--m-muted)]">
          or email
        </span>
      </div>

      <form onSubmit={onSubmit} className="space-y-3">
        <label className="block space-y-1">
          <span className="text-xs text-[var(--m-muted)]">Name (optional)</span>
          <input
            type="text"
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="m-ad-input"
          />
        </label>
        <label className="block space-y-1">
          <span className="text-xs text-[var(--m-muted)]">Email</span>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="m-ad-input"
          />
        </label>
        <label className="block space-y-1">
          <span className="text-xs text-[var(--m-muted)]">Password</span>
          <input
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="m-ad-input"
          />
        </label>
        <button type="submit" disabled={busy} className="m-btn-ghost w-full disabled:opacity-60">
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>

      <button
        type="button"
        onClick={onMagic}
        disabled={magicBusy}
        className="w-full mt-3 text-sm text-[var(--m-muted)] hover:text-white disabled:opacity-60"
      >
        {magicBusy ? "Sending link…" : "Email me a magic link instead"}
      </button>

      {error ? <p className="mt-3 text-sm text-[var(--m-hot)]">{error}</p> : null}
      {note ? <p className="mt-3 text-sm text-[var(--m-accent)]">{note}</p> : null}

      <p className="mt-5 text-xs text-[var(--m-muted)]">
        Already have an account?{" "}
        <Link
          href={`/login?next=${encodeURIComponent(dest())}`}
          className="text-white hover:underline"
        >
          Sign in
        </Link>
        . By continuing you agree to the{" "}
        <Link href="/terms" className="hover:underline">
          Terms
        </Link>{" "}
        and{" "}
        <Link href="/privacy" className="hover:underline">
          Privacy
        </Link>
        .
      </p>
    </div>
  );
}
