import type { Metadata } from "next";
import { Suspense } from "react";
import { AdSignupCard } from "@/components/marketing/AdSignupCard";
import { CaptureAdAttrs } from "@/components/marketing/CaptureAdAttrs";
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
      </Suspense>

      <section className="relative overflow-hidden border-b border-[var(--m-line)]">
        <div className="absolute inset-0 m-hero-stage" aria-hidden="true">
          <div className="m-hero-stage-grid">
            <WeekHeat dense />
          </div>
          <div className="m-hero-stage-veil" />
        </div>

        <div className="relative mx-auto max-w-6xl px-4 sm:px-5 pt-14 sm:pt-20 pb-16 sm:pb-24">
          <div className="grid lg:grid-cols-[1.1fr_0.9fr] gap-10 lg:gap-14 items-start">
            <div className="min-w-0">
              <p className="m-hero-brand m-brand text-[clamp(2.6rem,8vw,4.6rem)] leading-[0.9]">
                earnings<span>follower</span>
              </p>
              <h1 className="m-hero-line mt-7 max-w-xl text-xl sm:text-2xl text-white/90 leading-snug font-medium">
                See what&apos;s already priced into earnings — before you trade the
                print.
              </h1>
              <p className="m-hero-line m-hero-line-2 mt-4 max-w-md text-[var(--m-muted)] leading-relaxed">
                Free calendar with options-implied moves. Pro Drift and Waves boards
                when you want the follow-through.
              </p>
              <p className="m-hero-line m-hero-line-3 mt-8 text-[11px] uppercase tracking-[0.16em] text-[var(--m-muted)]">
                $0 to start · cancel Pro anytime · not financial advice
              </p>
            </div>

            <div className="m-hero-line m-hero-line-3 w-full max-w-md lg:max-w-none lg:justify-self-end">
              <AdSignupCard next="/calendar" />
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-5 py-14 sm:py-16">
        <h2 className="m-display text-2xl sm:text-3xl text-white tracking-tight max-w-lg">
          Built for earnings week — not another signal feed
        </h2>
        <p className="mt-4 max-w-xl text-[var(--m-muted)] leading-relaxed">
          We map the field (what&apos;s priced), then the follow-through (what usually
          happens after a print or a peer print). You decide what to do with it.
        </p>
        <ul className="mt-8 space-y-2.5 text-sm text-[var(--m-muted)] max-w-md">
          <li className="flex gap-2">
            <span className="text-[var(--m-accent)]">→</span>
            Who reports this week, with implied move when we have it
          </li>
          <li className="flex gap-2">
            <span className="text-[var(--m-accent)]">→</span>
            Reaction history on the company page
          </li>
          <li className="flex gap-2">
            <span className="text-[var(--m-accent)]">→</span>
            Optional Pro: live post-report Drift &amp; peer Waves
          </li>
        </ul>
      </section>
    </MarketingDataProvider>
  );
}
