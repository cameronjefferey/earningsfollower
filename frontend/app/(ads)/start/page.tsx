import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { AdCtas } from "@/components/marketing/AdCtas";
import { CaptureAdAttrs } from "@/components/marketing/CaptureAdAttrs";
import { TrackAdLanding } from "@/components/marketing/TrackAdLanding";
import { MarketingDataProvider } from "@/components/marketing/MarketingData";
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

const STEPS = [
  {
    title: "Browse free",
    body: "The full earnings calendar — who reports, when, and the options-implied move. No account needed.",
  },
  {
    title: "Go deeper",
    body: "Open any company for its reaction history: how it actually moved vs. what was priced in, quarter by quarter.",
  },
  {
    title: "Level up when ready",
    body: "A free account unlocks unlimited company pages and live prices. Pro adds the live Drift and Waves boards.",
  },
];

export default function AdStartPage() {
  return (
    <MarketingDataProvider>
      <Suspense fallback={null}>
        <CaptureAdAttrs />
        <TrackAdLanding />
      </Suspense>

      <section className="border-b border-[var(--m-line)]">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 pt-10 sm:pt-14 pb-12 sm:pb-16">
          <p className="m-hero-brand m-brand text-[clamp(2.2rem,6vw,3.4rem)] leading-[0.92]">
            earnings<span>follower</span>
          </p>
          <h1 className="m-hero-line mt-5 max-w-2xl text-lg sm:text-xl text-white/90 leading-snug font-medium">
            See what&apos;s already priced into this week&apos;s earnings.
          </h1>
          <p className="m-hero-line m-hero-line-2 mt-3 max-w-lg text-sm text-[var(--m-muted)] leading-relaxed">
            Free calendar with options-implied moves and reaction history. Browse it
            right now — no account needed.
          </p>

          <div className="m-hero-line m-hero-line-3 mt-7">
            <AdCtas />
          </div>

          <div className="mt-12">
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
            <p className="max-w-xl text-sm text-[var(--m-muted)] leading-relaxed mb-6">
              Real data, live now. Click any card for that company&apos;s full earnings
              story.
            </p>
            <div className="m-board-frame m-ad-priced">
              <WeekHeat limit={6} />
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-5 py-12 sm:py-14">
        <div className="grid sm:grid-cols-3 gap-6">
          {STEPS.map((s, i) => (
            <div key={s.title}>
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
          ))}
        </div>
        <p className="mt-10 text-[11px] uppercase tracking-[0.14em] text-[var(--m-muted)]">
          $0 to start · not financial advice
        </p>
      </section>
    </MarketingDataProvider>
  );
}
