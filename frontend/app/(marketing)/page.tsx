import type { Metadata } from "next";
import Link from "next/link";
import { BriefPeek } from "@/components/marketing/BriefPeek";
import { MarketingDataProvider } from "@/components/marketing/MarketingData";
import { Reveal } from "@/components/marketing/Reveal";
import { WeekHeat } from "@/components/marketing/WeekHeat";

export const metadata: Metadata = {
  title: "earningsfollower - priced-in calendar & trading boards",
  description:
    "Earnings research built around what’s already priced in options, plus live Waves and Drift boards for post-report continuation and peer setups.",
  alternates: { canonical: "https://www.earningsfollower.com/" },
};

export default function MarketingHomePage() {
  const softwareLd = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "earningsfollower",
    applicationCategory: "FinanceApplication",
    operatingSystem: "Web",
    url: "https://www.earningsfollower.com",
    description:
      "Priced-in earnings calendar plus Pro Waves and Drift boards for post-report continuation and peer-wave setups.",
    offers: [
      {
        "@type": "Offer",
        price: "0",
        priceCurrency: "USD",
        name: "Calendar",
        description: "Free earnings calendar with implied moves",
      },
      {
        "@type": "Offer",
        price: "9.99",
        priceCurrency: "USD",
        name: "Pro",
        description: "Live Waves and Drift boards, billed monthly",
      },
    ],
  };

  return (
    <MarketingDataProvider>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(softwareLd) }}
      />

      <section className="relative overflow-hidden border-b border-[var(--m-line)]">
        <div className="absolute inset-0 m-hero-stage" aria-hidden="true">
          <div className="m-hero-stage-grid">
            <WeekHeat dense />
          </div>
          <div className="m-hero-stage-veil" />
        </div>

        <div className="relative mx-auto max-w-6xl px-4 sm:px-5 pt-20 sm:pt-28 pb-24 sm:pb-32 min-h-[68vh]">
          <p className="m-hero-brand m-brand text-[clamp(2.9rem,9vw,5.5rem)] leading-[0.88]">
            earnings<span>follower</span>
          </p>
          <h1 className="m-hero-line mt-8 max-w-2xl text-xl sm:text-2xl text-white/90 leading-snug font-medium">
            A map of what&apos;s priced in - then what usually happens after a name
            reports, and after a peer reports.
          </h1>
          <p className="m-hero-line m-hero-line-2 mt-4 max-w-lg text-[var(--m-muted)]">
            Calendar for the field. Waves and Drift boards when you&apos;re ready to
            trade the follow-through.
          </p>
          <div className="m-hero-line m-hero-line-3 mt-9 flex flex-wrap items-center gap-3">
            <Link href="/login?mode=signup&next=/calendar" className="m-btn-primary">
              Sign up
            </Link>
            <Link href="/calendar" className="m-btn-ghost">
              Open the calendar
            </Link>
          </div>
          <p className="m-hero-line m-hero-line-3 mt-10 text-[11px] uppercase tracking-[0.18em] text-[var(--m-muted)]">
            This week&apos;s field · options-implied moves · live
          </p>
        </div>
      </section>

      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-14 sm:py-16">
          <Reveal>
            <h2 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight max-w-xl">
              Three things we actually do
            </h2>
          </Reveal>
          <div className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-6">
            {[
              {
                n: "01",
                t: "Priced-in",
                d: "Who reports, and what options already baked into the move. Scan the week without pretending we know the EPS.",
              },
              {
                n: "02",
                t: "After it reports",
                d: "Peer waves into the next name. Drift after a strong report. History with n attached - thin samples get called thin.",
              },
              {
                n: "03",
                t: "Boards",
                d: "Live Waves and Drift - post-earnings continuation and peer setups, with sample size attached. Trade from the board, not a catalog.",
              },
            ].map((s, i) => (
              <Reveal key={s.t} delayMs={i * 50}>
                <div className="m-step h-full">
                  <div className="m-step-n tabular">{s.n}</div>
                  <h3 className="mt-4 text-lg font-semibold text-white">{s.t}</h3>
                  <p className="mt-2 text-sm text-[var(--m-muted)] leading-relaxed">
                    {s.d}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-16 sm:py-20">
          <Reveal>
            <div className="flex flex-wrap items-end justify-between gap-4 mb-3">
              <h2 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight">
                What&apos;s already priced in
              </h2>
              <Link href="/calendar" className="text-sm text-[var(--m-accent)] hover:underline">
                Full calendar →
              </Link>
            </div>
            <p className="max-w-xl text-[var(--m-muted)] leading-relaxed mb-8">
              Top names this week by options-implied move - with date, history, and theme
              on each card.
            </p>
          </Reveal>
          <Reveal delayMs={40}>
            <div className="m-board-frame">
              <WeekHeat />
            </div>
          </Reveal>
        </div>
      </section>

      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-16 sm:py-20 grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-12">
          <div className="lg:col-span-5 space-y-8">
            <Reveal>
              <h2 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight">
                Follow-through after it reports
              </h2>
              <p className="mt-4 text-[var(--m-muted)] leading-relaxed">
                Boards surface peer waves (a related name already reported) and
                post-earnings drift (the report already landed). Sample size stays on the
                card. If history is junk, we say so.
              </p>
            </Reveal>
            <Reveal delayMs={40}>
              <ul className="space-y-4 text-sm text-[var(--m-muted)]">
                <li className="border-l-2 border-[var(--m-accent)] pl-3">
                  <span className="text-white font-medium">Wave</span> - ride transmission
                  into the next peer report
                </li>
                <li className="border-l-2 border-[var(--m-warm)] pl-3">
                  <span className="text-white font-medium">Drift</span> - after a strong
                  report, history on whether the move kept going
                </li>
                <li className="border-l-2 border-[var(--m-line)] pl-3">
                  <span className="text-white font-medium">Drop-if</span> - explicit kill
                  switch so you&apos;re not inventing one mid-session
                </li>
              </ul>
            </Reveal>
            <Reveal delayMs={80}>
              <div className="rounded-lg border border-[var(--m-accent)]/30 bg-[var(--m-accent)]/5 p-4 text-sm text-[var(--m-muted)] leading-relaxed">
                Waves are why this site exists. The founder watched MDB and SNOW
                rip, rode the wave into Oracle&apos;s report, and made{" "}
                <span className="text-white font-medium tabular">+150%</span>.
                One trade, not a promise - but it&apos;s the setup the Waves board
                hunts every season.
              </div>
            </Reveal>
            <Reveal delayMs={100}>
              <Link href="/how-it-works" className="text-sm text-[var(--m-accent)] hover:underline">
                How waves &amp; drift work →
              </Link>
            </Reveal>
          </div>
          <div className="lg:col-span-7">
            <Reveal delayMs={60}>
              <BriefPeek />
            </Reveal>
          </div>
        </div>
      </section>

      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-14 sm:py-16 grid grid-cols-1 md:grid-cols-12 gap-8 items-center">
          <div className="md:col-span-7">
            <Reveal>
              <h2 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight max-w-lg">
                Built for people who already trade earnings
              </h2>
              <p className="mt-4 text-[var(--m-muted)] leading-relaxed max-w-md">
                If you live in Finviz + Twitter + a spreadsheet all quarter, this cuts that
                down. If you want a buy list or a secret EPS, keep walking.
              </p>
            </Reveal>
          </div>
          <div className="md:col-span-5">
            <Reveal delayMs={80}>
              <div className="m-stat-row">
                <div>
                  <div className="m-stat-label">Map</div>
                  <div className="m-stat-value">Priced-in</div>
                </div>
                <div className="m-stat-div" />
                <div>
                  <div className="m-stat-label">Habit</div>
                  <div className="m-stat-value">One focus</div>
                </div>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      <section className="relative overflow-hidden">
        <div className="absolute inset-0 opacity-30 pointer-events-none" aria-hidden="true">
          <WeekHeat dense />
        </div>
        <div className="absolute inset-0 bg-gradient-to-r from-[var(--m-bg)] via-[var(--m-bg)]/95 to-[var(--m-bg)]/70" />
        <div className="relative mx-auto max-w-6xl px-4 sm:px-5 py-16 sm:py-20">
          <Reveal>
            <h2 className="text-3xl sm:text-4xl font-semibold text-white tracking-tight">
              Start with the map
            </h2>
            <p className="mt-4 max-w-md text-[var(--m-muted)] leading-relaxed">
              See what&apos;s priced for this week. When reports start landing, open
              Waves and Drift.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/login?mode=signup&next=/calendar" className="m-btn-primary">
                Create account
              </Link>
              <Link href="/calendar" className="m-btn-ghost">
                Live calendar
              </Link>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-5 py-10">
        <p className="text-xs text-[var(--m-muted)] max-w-xl leading-relaxed">
          Research only - not advice. Data from Financial Modeling Prep and Yahoo Finance
          can be late or wrong. Implied moves are ATM-straddle estimates.
        </p>
      </section>
    </MarketingDataProvider>
  );
}
