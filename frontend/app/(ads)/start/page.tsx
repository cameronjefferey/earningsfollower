import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { AdCtas } from "@/components/marketing/AdCtas";
import { CaptureAdAttrs } from "@/components/marketing/CaptureAdAttrs";
import { TrackAdLanding } from "@/components/marketing/TrackAdLanding";
import { MarketingDataProvider } from "@/components/marketing/MarketingData";
import { Reveal } from "@/components/marketing/Reveal";
import { WeekHeat } from "@/components/marketing/WeekHeat";
import { WeekPulse } from "@/components/marketing/WeekPulse";

export const metadata: Metadata = {
  title: "Find the mispriced earnings moves | free calendar",
  description:
    "The options market names a price for every earnings report. Some of those prices are wrong. See where, free, with no account needed.",
  alternates: { canonical: "https://www.earningsfollower.com/start" },
  openGraph: {
    title: "earningsfollower: find the mispriced earnings moves",
    description:
      "What options price in vs. what actually happens, for every report this week. Free to browse.",
    url: "https://www.earningsfollower.com/start",
  },
};

const VALUE = [
  {
    title: "Find the gap",
    body: "When options price a ±5% move on a name that averages ±12%, that gap is the trade. The calendar puts both numbers on every card so mispricings jump out instead of hiding in an option chain.",
  },
  {
    title: "Skip the coin flips",
    body: "Half the edge is knowing when there isn't one. If a name does exactly what options price, quarter after quarter, you pass and keep your capital for the setups with a real gap.",
  },
  {
    title: "Three minutes, not three hours",
    body: "One screen replaces Finviz, a chain-by-chain straddle check, and the spreadsheet where you track how names actually react. Scan the week over coffee, go deep only where it's worth it.",
  },
];

export default function AdStartPage() {
  return (
    <MarketingDataProvider>
      <Suspense fallback={null}>
        <CaptureAdAttrs />
        <TrackAdLanding />
      </Suspense>

      {/* Hero: the payoff, not the product. */}
      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 pt-10 sm:pt-14 pb-12 sm:pb-16">
          <p className="m-hero-brand m-brand text-[clamp(2.2rem,6vw,3.4rem)] leading-[0.92]">
            earnings<span>follower</span>
          </p>
          <h1 className="m-hero-line mt-5 max-w-2xl text-2xl sm:text-3xl text-white leading-tight font-semibold tracking-tight">
            Some earnings moves are mispriced. Find them before the print.
          </h1>
          <p className="m-hero-line m-hero-line-2 mt-4 max-w-xl text-sm sm:text-base text-[var(--m-muted)] leading-relaxed">
            Before every report, the options market names its price for the move.
            History says how that name actually behaves. When those two disagree,
            you have a trade. That comparison is on every card, free.
          </p>

          <div className="m-hero-line m-hero-line-3 mt-7">
            <AdCtas placement="hero" primary="signup" />
          </div>

          <div className="m-hero-line m-hero-line-3 mt-8">
            <WeekPulse />
          </div>
        </div>
      </section>

      {/* Live proof: the actual board, then a browse CTA. */}
      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-12 sm:py-16">
          <Reveal>
            <div className="flex flex-wrap items-end justify-between gap-3 mb-2">
              <h2 className="text-xl sm:text-2xl font-semibold text-white tracking-tight">
                Live right now: this week, ranked by implied move
              </h2>
              <Link
                href="/calendar"
                className="text-sm text-[var(--m-accent)] hover:underline"
              >
                Full calendar →
              </Link>
            </div>
            <p className="max-w-xl text-sm text-[var(--m-muted)] leading-relaxed mb-4 sm:mb-6">
              Not a screenshot. This is the real board, and every card opens that
              company&apos;s full earnings story: what was priced, what happened.
            </p>
          </Reveal>
          <Reveal delayMs={40}>
            <div className="m-board-frame m-ad-priced">
              <WeekHeat limit={6} />
            </div>
          </Reveal>
          <Reveal delayMs={80}>
            <div className="mt-6">
              <AdCtas placement="board" primary="browse" />
            </div>
          </Reveal>
        </div>
      </section>

      {/* The value: what you walk away with each week. */}
      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-12 sm:py-16">
          <Reveal>
            <h2 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight max-w-xl">
              What this is worth to you
            </h2>
            <p className="mt-3 max-w-xl text-sm text-[var(--m-muted)] leading-relaxed">
              Not another feed to check. An edge you take into every earnings week.
            </p>
          </Reveal>
          <div className="mt-8 sm:mt-10 grid grid-cols-1 md:grid-cols-3 gap-6">
            {VALUE.map((v, i) => (
              <Reveal key={v.title} delayMs={i * 50}>
                <div className="m-step h-full">
                  <h3 className="text-lg font-semibold text-white">{v.title}</h3>
                  <p className="mt-2 text-sm text-[var(--m-muted)] leading-relaxed">
                    {v.body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
          <Reveal delayMs={120}>
            <div className="mt-8 sm:mt-10">
              <AdCtas placement="value" primary="signup" />
              <p className="mt-3 text-xs text-[var(--m-muted)]">
                Free account = unlimited company pages and live prices. No card
                required, cancel nothing. It&apos;s free.
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      {/* Objection handling: who this is for, in one honest breath. */}
      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-12 sm:py-16 grid grid-cols-1 md:grid-cols-12 gap-8 items-center">
          <div className="md:col-span-7">
            <Reveal>
              <h2 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight max-w-lg">
                No picks. No gurus. Just the two numbers that matter.
              </h2>
              <p className="mt-4 text-[var(--m-muted)] leading-relaxed max-w-md text-sm sm:text-base">
                We won&apos;t tell you what to buy, and we don&apos;t pretend to know
                the EPS. We show what the market is pricing and what history says
                about it: the homework you&apos;d do yourself if you had the time.
                The trade stays yours.
              </p>
            </Reveal>
          </div>
          <div className="md:col-span-5">
            <Reveal delayMs={80}>
              <div className="m-stat-row">
                <div>
                  <div className="m-stat-label">Priced in</div>
                  <div className="m-stat-value">On every card</div>
                </div>
                <div className="m-stat-div" />
                <div>
                  <div className="m-stat-label">History</div>
                  <div className="m-stat-value">8+ quarters</div>
                </div>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* Closing CTA banner. */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 opacity-30 pointer-events-none" aria-hidden="true">
          <WeekHeat dense />
        </div>
        <div className="absolute inset-0 bg-gradient-to-r from-[var(--m-bg)] via-[var(--m-bg)]/95 to-[var(--m-bg)]/70" />
        <div className="relative mx-auto max-w-6xl px-4 sm:px-5 py-14 sm:py-20">
          <Reveal>
            <h2 className="text-3xl sm:text-4xl font-semibold text-white tracking-tight max-w-lg">
              The market already named its price. Go see if it&apos;s wrong.
            </h2>
            <p className="mt-4 max-w-md text-[var(--m-muted)] leading-relaxed">
              This week&apos;s calendar is live and free. Create a free account for
              unlimited company pages and live prices. Pro adds the boards when
              you&apos;re ready.
            </p>
            <div className="mt-8">
              <AdCtas placement="bottom" primary="signup" />
            </div>
            <p className="mt-8 text-[11px] uppercase tracking-[0.14em] text-[var(--m-muted)]">
              $0 to start · no card required · not financial advice
            </p>
          </Reveal>
        </div>
      </section>
    </MarketingDataProvider>
  );
}
