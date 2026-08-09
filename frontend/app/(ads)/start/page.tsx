import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { AdCtas } from "@/components/marketing/AdCtas";
import { CaptureAdAttrs } from "@/components/marketing/CaptureAdAttrs";
import { TrackAdLanding } from "@/components/marketing/TrackAdLanding";
import { MarketingDataProvider } from "@/components/marketing/MarketingData";
import { Reveal } from "@/components/marketing/Reveal";
import { WeekHeat } from "@/components/marketing/WeekHeat";

export const metadata: Metadata = {
  title: "Free earnings calendar — see what's priced in",
  description:
    "Who reports this week and what the options market expects. Browse free — no account needed. Company pages, reaction history, and Pro boards when you're ready.",
  alternates: { canonical: "https://www.earningsfollower.com/start" },
  openGraph: {
    title: "earningsfollower — what's already priced into earnings",
    description:
      "Free earnings calendar with options-implied moves. Browse without an account.",
    url: "https://www.earningsfollower.com/start",
  },
};

const FEATURES = [
  {
    n: "01",
    tag: "Free",
    title: "The priced-in calendar",
    body: "Every name reporting this week with its options-implied move — the size of the move traders are actually paying for. Scan the field in one screen instead of digging through option chains ticker by ticker.",
  },
  {
    n: "02",
    tag: "Free",
    title: "Company reaction pages",
    body: "Open any name for its earnings history: what was priced in vs. how the stock actually moved, quarter by quarter, with up rate and average move. That's the context for whether this quarter's expected move looks rich or cheap.",
  },
  {
    n: "03",
    tag: "Pro",
    title: "Drift & Waves boards",
    body: "After reports land: post-earnings drift (does a strong report keep going?) and peer waves (a rival just moved — history on whether it transmits). Live boards with sample size attached, so thin history gets called thin.",
  },
];

const STEPS = [
  {
    title: "Scan the week",
    body: "The calendar ranks who reports by implied move. A ±9% print on the card means the market is braced for a big one.",
  },
  {
    title: "Open the name",
    body: "The company page shows the last eight-plus quarters: expected move vs. actual move. You see instantly if this name routinely blows through what options price.",
  },
  {
    title: "Make the call",
    body: "Now you know what's priced in and how it usually resolves. Trade it, fade it, or skip it — with context instead of a headline.",
  },
];

export default function AdStartPage() {
  return (
    <MarketingDataProvider>
      <Suspense fallback={null}>
        <CaptureAdAttrs />
        <TrackAdLanding />
      </Suspense>

      {/* Hero: what the product is, in one breath, then proof right below. */}
      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 pt-10 sm:pt-14 pb-12 sm:pb-16">
          <p className="m-hero-brand m-brand text-[clamp(2.2rem,6vw,3.4rem)] leading-[0.92]">
            earnings<span>follower</span>
          </p>
          <h1 className="m-hero-line mt-5 max-w-2xl text-lg sm:text-xl text-white/90 leading-snug font-medium">
            Before every earnings report, the options market names its price. We put
            that number on every card — next to what actually happened last time.
          </h1>
          <p className="m-hero-line m-hero-line-2 mt-3 max-w-lg text-sm text-[var(--m-muted)] leading-relaxed">
            A free earnings calendar built around one question: what&apos;s already
            priced in? Browse it right now — no account needed.
          </p>

          <div className="m-hero-line m-hero-line-3 mt-7">
            <AdCtas placement="hero" primary="browse" />
          </div>

          <div className="mt-8 sm:mt-12">
            <div className="flex flex-wrap items-end justify-between gap-3 mb-2">
              <h2 className="text-xl sm:text-2xl font-semibold text-white tracking-tight">
                This week, ranked by implied move
              </h2>
              <Link
                href="/calendar"
                className="text-sm text-[var(--m-accent)] hover:underline"
              >
                Full calendar →
              </Link>
            </div>
            <p className="max-w-xl text-sm text-[var(--m-muted)] leading-relaxed mb-4 sm:mb-6">
              Real data, live now. Click any card for that company&apos;s full earnings
              story.
            </p>
            <div className="m-board-frame m-ad-priced">
              <WeekHeat limit={6} />
            </div>
          </div>
        </div>
      </section>

      {/* What you actually get — the product, explained. */}
      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-12 sm:py-16">
          <Reveal>
            <h2 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight max-w-xl">
              What you actually get
            </h2>
            <p className="mt-3 max-w-xl text-sm text-[var(--m-muted)] leading-relaxed">
              No buy lists, no secret EPS calls. Three tools for reading earnings
              season the way options traders do.
            </p>
          </Reveal>
          <div className="mt-8 sm:mt-10 grid grid-cols-1 md:grid-cols-3 gap-6">
            {FEATURES.map((f, i) => (
              <Reveal key={f.title} delayMs={i * 50}>
                <div className="m-step h-full">
                  <div className="flex items-center justify-between">
                    <div className="m-step-n tabular">{f.n}</div>
                    <span
                      className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                        f.tag === "Free"
                          ? "bg-[var(--m-accent)]/15 text-[var(--m-accent)]"
                          : "bg-white/10 text-white/80"
                      }`}
                    >
                      {f.tag}
                    </span>
                  </div>
                  <h3 className="mt-4 text-lg font-semibold text-white">{f.title}</h3>
                  <p className="mt-2 text-sm text-[var(--m-muted)] leading-relaxed">
                    {f.body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
          <Reveal delayMs={120}>
            <div className="mt-8 sm:mt-10">
              <AdCtas placement="features" primary="signup" />
              <p className="mt-3 text-xs text-[var(--m-muted)]">
                Free account = unlimited company pages and live prices. No card
                required.
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      {/* How a trader actually uses it — concrete, not feature-speak. */}
      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-12 sm:py-16">
          <Reveal>
            <h2 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight max-w-xl">
              How it fits into your week
            </h2>
          </Reveal>
          <div className="mt-8 grid sm:grid-cols-3 gap-6">
            {STEPS.map((s, i) => (
              <Reveal key={s.title} delayMs={i * 50}>
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--m-accent)] mb-2">
                    Step {i + 1}
                  </div>
                  <h3 className="text-base font-semibold text-white tracking-tight">
                    {s.title}
                  </h3>
                  <p className="mt-2 text-sm text-[var(--m-muted)] leading-relaxed">
                    {s.body}
                  </p>
                </div>
              </Reveal>
            ))}
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
              Know what&apos;s priced in before the market opens.
            </h2>
            <p className="mt-4 max-w-md text-[var(--m-muted)] leading-relaxed">
              The calendar is free to browse right now. A free account unlocks
              unlimited company pages and live prices — Pro adds the live boards when
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
