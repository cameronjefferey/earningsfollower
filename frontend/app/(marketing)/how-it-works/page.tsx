import type { Metadata } from "next";
import Link from "next/link";
import { Reveal } from "@/components/marketing/Reveal";

export const metadata: Metadata = {
  title: "How it works",
  description:
    "Priced-in calendar, peer waves, and post-report drift boards - the research surfaces you trade from.",
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
        Priced-in map. Follow-through after a name reports and after a peer reports -
        on live Waves and Drift boards.
      </p>

      <div className="mt-12 space-y-12 text-[var(--m-muted)] leading-relaxed">
        <Reveal>
          <h2 className="m-display text-xl text-[var(--m-ink)]">Priced-in calendar</h2>
          <p className="mt-3">
            Who reports, BMO/AMC, themes, market cap, and an options-implied move when we
            can estimate one. That&apos;s the field - what the market already baked in -
            not a secret EPS.
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
            report, and turned $50k into $125k. The Waves board exists to find that
            setup systematically: every group, who reported, who ripped, and who&apos;s
            still waiting. One trade, not a promise - every wave carries its history
            and sample size.
          </p>
        </Reveal>

        <Reveal delayMs={60}>
          <h2 className="m-display text-xl text-[var(--m-ink)]">Drift: after it reports</h2>
          <p className="mt-3">
            <span className="text-[var(--m-ink)]">Post-earnings drift</span> - the report
            already landed; history on whether similar reports kept moving (or faded),
            with sample size attached.
          </p>
        </Reveal>

        <Reveal delayMs={80}>
          <h2 className="m-display text-xl text-[var(--m-ink)]">Trade from the board</h2>
          <p className="mt-3">
            Open{" "}
            <span className="text-[var(--m-ink)]">Waves</span> or{" "}
            <span className="text-[var(--m-ink)]">Drift</span>, filter by sample quality,
            and work the live list. Calendar&apos;s Today strip can point you at a board
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
