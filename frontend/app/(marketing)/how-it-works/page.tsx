import type { Metadata } from "next";
import Link from "next/link";
import { Reveal } from "@/components/marketing/Reveal";

export const metadata: Metadata = {
  title: "How it works",
  description:
    "Priced-in calendar for $10B+ names, peer waves, and the week's 5-day losers.",
  alternates: {
    canonical: "https://www.earningsfollower.com/how-it-works",
  },
};

export default function HowItWorksPage() {
  return (
    <article className="mx-auto max-w-2xl px-5 sm:px-6 py-14 sm:py-20">
      <h1 className="m-display m-hero-brand text-3xl sm:text-4xl text-[var(--m-ink)] tracking-tight">
        How it works
      </h1>
      <p className="m-hero-line mt-5 text-lg text-[var(--m-muted)] leading-relaxed">
        Priced-in map for large caps. Peer waves into the next report, and the
        week&apos;s worst 5-day losers.
      </p>

      <div className="mt-12 space-y-12 text-[var(--m-muted)] leading-relaxed">
        <Reveal>
          <h2 className="m-display text-xl text-[var(--m-ink)]">Priced-in calendar</h2>
          <p className="mt-3">
            Who reports, BMO/AMC, themes, market cap, and an options-implied move when we
            can estimate one. The calendar is $10B+ and leaves application software
            off - the same bar as the live book.
          </p>
          <p className="mt-3">
            Company pages hold the reaction history. The calendar stays usable without
            paying.
          </p>
        </Reveal>

        <Reveal delayMs={40}>
          <h2 className="m-display text-xl text-[var(--m-ink)]">
            Waves: the reason this site exists
          </h2>
          <p className="mt-3">
            Names in a group move together around earnings. When peers blow through
            their numbers, the market starts re-pricing the names in that group that
            haven&apos;t reported yet. That run-up into the next report is a{" "}
            <span className="text-[var(--m-ink)]">wave</span>.
          </p>
          <p className="mt-3">
            The founder watched MDB and SNOW rip, rode the wave into Oracle&apos;s
            report, and made +150%. The Waves board exists to find that setup
            systematically: every group, who reported, who ripped, and who&apos;s
            still waiting. One trade, not a promise - every wave carries its history
            and sample size.
          </p>
        </Reveal>

        <Reveal delayMs={60}>
          <h2 className="m-display text-xl text-[var(--m-ink)]">5-day losers</h2>
          <p className="mt-3">
            The worst five-session drops in the S&amp;P 500. Names with earnings
            too close are left off. The same short list the book ranks each week.
          </p>
        </Reveal>

        <Reveal delayMs={80}>
          <h2 className="m-display text-xl text-[var(--m-ink)]">Trade from the board</h2>
          <p className="mt-3">
            Open{" "}
            <span className="text-[var(--m-ink)]">Waves</span> or the{" "}
            <span className="text-[var(--m-ink)]">5-day losers</span>, and work the
            live list. Calendar&apos;s Today strip can point you at a board
            when something&apos;s hot - without a separate brief page.
          </p>
        </Reveal>

        <Reveal delayMs={120}>
          <h2 className="m-display text-xl text-[var(--m-ink)]">Sample honesty</h2>
          <p className="mt-3">
            Thin history gets called out. Win rate sits next to n. If the sample is junk,
            skip it - we&apos;d rather look boring than confident.
          </p>
        </Reveal>

        <Reveal delayMs={160}>
          <h2 className="m-display text-xl text-[var(--m-ink)]">What this isn&apos;t</h2>
          <p className="mt-3">
            Not a secret-EPS service. Not an autotrader. Not a return promise. Not a pile
            of push alerts.
          </p>
        </Reveal>
      </div>

      <Reveal delayMs={80}>
        <div className="mt-14 flex flex-wrap gap-3">
          <Link href="/calendar" className="m-btn-primary">
            Open calendar
          </Link>
          <Link href="/boards" className="m-btn-ghost">
            Boards
          </Link>
        </div>
      </Reveal>
    </article>
  );
}
