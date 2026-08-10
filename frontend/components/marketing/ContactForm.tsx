"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { API_BASE } from "@/lib/api";

export function ContactForm() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [honeypot, setHoneypot] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          message: message.trim(),
          website: honeypot,
        }),
        cache: "no-store",
      });
      const data = (await res.json().catch(() => ({}))) as {
        detail?: unknown;
        message?: string;
      };
      if (!res.ok) {
        const detail = data.detail;
        let msg = `Could not send (${res.status})`;
        if (typeof detail === "string") msg = detail;
        else if (Array.isArray(detail) && detail[0]?.msg) msg = String(detail[0].msg);
        setError(msg);
        return;
      }
      setDone(true);
    } catch {
      setError("Could not reach the server. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="mt-10 space-y-4">
        <p className="text-[var(--m-ink)] leading-relaxed">
          Thanks - your message is on its way. We&apos;ll reply by email.
        </p>
        <Link href="/faq" className="m-btn-ghost inline-flex">
          Back to FAQ
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="mt-10 space-y-4 relative">
      <label className="block space-y-1.5">
        <span className="text-xs uppercase tracking-wide text-[var(--m-muted)]">
          Name
        </span>
        <input
          type="text"
          required
          maxLength={120}
          autoComplete="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded-lg border border-[var(--m-line)] bg-[var(--m-bg-elev)] px-3 py-2.5 text-sm text-[var(--m-ink)] outline-none focus:border-[var(--m-accent)]"
        />
      </label>
      <label className="block space-y-1.5">
        <span className="text-xs uppercase tracking-wide text-[var(--m-muted)]">
          Email
        </span>
        <input
          type="email"
          required
          maxLength={320}
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-lg border border-[var(--m-line)] bg-[var(--m-bg-elev)] px-3 py-2.5 text-sm text-[var(--m-ink)] outline-none focus:border-[var(--m-accent)]"
        />
      </label>
      <label className="block space-y-1.5">
        <span className="text-xs uppercase tracking-wide text-[var(--m-muted)]">
          Message
        </span>
        <textarea
          required
          minLength={10}
          maxLength={5000}
          rows={6}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          className="w-full rounded-lg border border-[var(--m-line)] bg-[var(--m-bg-elev)] px-3 py-2.5 text-sm text-[var(--m-ink)] outline-none focus:border-[var(--m-accent)] resize-y"
        />
      </label>

      <div className="absolute -left-[9999px] opacity-0 h-0 w-0 overflow-hidden" aria-hidden>
        <label>
          Website
          <input
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={honeypot}
            onChange={(e) => setHoneypot(e.target.value)}
          />
        </label>
      </div>

      {error ? <p className="text-sm text-[var(--color-down)]">{error}</p> : null}

      <button type="submit" disabled={busy} className="m-btn-primary disabled:opacity-60">
        {busy ? "Sending…" : "Send message"}
      </button>
    </form>
  );
}
