import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { AdSignupCard } from "@/components/marketing/AdSignupCard";
import { CaptureAdAttrs } from "@/components/marketing/CaptureAdAttrs";
import { TrackAdLanding } from "@/components/marketing/TrackAdLanding";
import { MarketingDataProvider } from "@/components/marketing/MarketingData";
import { WeekHeat } from "@/components/marketing/WeekHeat";

export const metadata: Metadata = {
  title: "Start free — priced-in earnings calendar",
  description:
    "Create a free earningsfollower account. See what’s priced into this week’s reports — then unlock Drift and Waves boards when you’re ready.",
  alternates: { canonical: "https://www.earningsfollower.com/start" },
  openGraph: {
    title: "earningsfollower — start free",
    description:
      "Free priced-in earnings calendar. Pro boards for post-report drift and peer waves.",
    url: "https://www.earningsfollower.com/start",
  },
};

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
            See what&apos;s already priced into earnings — before you trade the print.
          </h1>
          <p className="m-hero-line m-hero-line-2 mt-3 max-w-lg text-sm text-[var(--m-muted)] leading-relaxed">
            Free calendar with options-implied moves. Pro boards when you want the
            follow-through.
          </p>

          <div className="m-hero-line m-hero-line-3 mt-10 grid lg:grid-cols-12 gap-8 lg:gap-10 items-start">
            <div className="lg:col-span-7 order-2 lg:order-1 min-w-0">
              <div className="flex flex-wrap items-end justify-between gap-3 mb-2">
                <h2 className="text-xl sm:text-2xl font-semibold text-white tracking-tight">
                  What&apos;s already priced in
                </h2>
                <Link
                  href="/calendar"
                  className="text-sm text-[var(--m-accent)] hover:underline"
                >
                  Full calendar →
                </Link>
              </div>
              <p className="max-w-xl text-sm text-[var(--m-muted)] leading-relaxed mb-6">
                Top names this week by options-implied move — with date, history, and
                theme on each card.
              </p>
              <div className="m-board-frame m-ad-priced">
                <WeekHeat limit={4} />
              </div>
            </div>

            <div className="lg:col-span-5 order-1 lg:order-2 w-full max-w-md lg:max-w-none lg:sticky lg:top-20">
              <AdSignupCard next="/calendar" />
              <p className="mt-3 text-[11px] uppercase tracking-[0.14em] text-[var(--m-muted)] text-center lg:text-left">
                $0 to start · not financial advice
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-5 py-12 sm:py-14">
        <h2 className="m-display text-2xl text-white tracking-tight max-w-lg">
          Built for earnings week — not another signal feed
        </h2>
        <p className="mt-3 max-w-xl text-sm text-[var(--m-muted)] leading-relaxed">
          We map the field (what&apos;s priced), then the follow-through after a print or
          a peer print. You decide what to do with it.
        </p>
      </section>
    </MarketingDataProvider>
  );
}
