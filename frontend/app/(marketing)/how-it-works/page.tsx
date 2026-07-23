import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "How it works",
  description:
    "How earningsfollower’s free earnings calendar and Pro morning brief fit together — implied moves, focus setups, and drop-if rules.",
  alternates: {
    canonical: "https://www.earningsfollower.com/how-it-works",
  },
};

export default function HowItWorksPage() {
  return (
    <article className="mx-auto max-w-2xl px-5 sm:px-6 py-14 sm:py-20">
      <h1 className="m-display text-3xl sm:text-4xl text-[var(--m-ink)] tracking-tight">
        How it works
      </h1>
      <p className="mt-5 text-lg text-[var(--m-muted)] leading-relaxed">
        Short version: the calendar shows the field. The brief names a lean. You keep the
        kill switch.
      </p>

      <div className="mt-12 space-y-12 text-[var(--m-muted)] leading-relaxed">
        <section>
          <h2 className="m-display text-xl text-[var(--m-ink)]">1. Calendar</h2>
          <p className="mt-3">
            We pull upcoming (and recent) earnings for a curated universe — timing (BMO/AMC),
            market cap, theme tags, and an options-implied move when we can estimate one from
            ATM straddles. Filters are for “who matters this week,” not for building a
            watchlist empire.
          </p>
          <p className="mt-3">
            Company pages dig into historical reactions. That research is what the brief
            ranks from; the calendar is the public map.
          </p>
        </section>

        <section>
          <h2 className="m-display text-xl text-[var(--m-ink)]">2. Morning brief</h2>
          <p className="mt-3">
            Pro runs a ranked setup list each session. Usually that means peer waves (a
            related name already reported) or post-earnings drift (the print already
            happened and history says the move tends to continue — or fade).
          </p>
          <p className="mt-3">
            You get one focus card first: ticker, headline, historical edge when we have
            sample, then{" "}
            <span className="text-[var(--m-ink)]">action / watch / drop-if</span>. A short
            board sits underneath. “What changed” and “printing today” keep context without
            turning the page into a dashboard.
          </p>
        </section>

        <section>
          <h2 className="m-display text-xl text-[var(--m-ink)]">3. Honesty on the sample</h2>
          <p className="mt-3">
            Thin history gets labeled. Win rates sit next to n. If the sample is junk, we
            say so — better a skipped trade than a confident fiction.
          </p>
        </section>

        <section>
          <h2 className="m-display text-xl text-[var(--m-ink)]">What we don&apos;t do</h2>
          <p className="mt-3">
            We don&apos;t auto-trade your account on the research product. We don&apos;t
            promise returns. We don&apos;t spam twelve “alerts” that all say the same thing.
            Paper trading and internal tools exist for the operator; they&apos;re not the
            public pitch.
          </p>
        </section>
      </div>

      <div className="mt-14 flex flex-wrap gap-3">
        <Link
          href="/calendar"
          className="rounded-md bg-[var(--m-ink)] text-[var(--m-panel)] px-4 py-2.5 text-sm font-semibold hover:bg-[var(--m-accent)] transition-colors"
        >
          Open calendar
        </Link>
        <Link
          href="/pricing"
          className="rounded-md border border-[var(--m-line)] bg-[var(--m-panel)] px-4 py-2.5 text-sm font-medium hover:border-[var(--m-accent)] transition-colors"
        >
          Pro pricing
        </Link>
      </div>
    </article>
  );
}
