import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "earningsfollower — earnings calendar & morning brief",
  description:
    "Free earnings calendar with implied moves. Pro morning brief picks one focus setup: what to lean on, what to watch, and when to drop it.",
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
      "Free earnings calendar with implied moves, plus a Pro morning brief with one focus setup — action, watch, and drop-if.",
    offers: [
      {
        "@type": "Offer",
        price: "0",
        priceCurrency: "USD",
        name: "Calendar",
        description: "Free earnings calendar",
      },
      {
        "@type": "Offer",
        price: "9.99",
        priceCurrency: "USD",
        name: "Pro",
        description: "Morning brief subscription, billed monthly",
      },
    ],
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(softwareLd) }}
      />
      <section className="relative overflow-hidden">
        <div className="mx-auto max-w-5xl px-5 sm:px-6 pt-14 sm:pt-20 pb-10 sm:pb-14">
          <p className="m-display m-settle text-4xl sm:text-6xl md:text-7xl tracking-tight text-[var(--m-ink)] leading-[1.05]">
            earningsfollower
          </p>
          <h1 className="m-display m-settle-delay mt-6 max-w-xl text-2xl sm:text-3xl text-[var(--m-ink)] leading-snug font-medium">
            Who prints this week. What the market already priced in. One thing to lean on before the open.
          </h1>
          <p className="m-settle-delay-2 mt-5 max-w-md text-base sm:text-lg text-[var(--m-muted)] leading-relaxed">
            Calendar is free. The morning brief is Pro — a ranked focus with an action, a
            watch, and a drop-if. Not another board of fifty names.
          </p>
          <div className="m-settle-delay-2 mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/calendar"
              className="inline-flex rounded-md bg-[var(--m-ink)] text-[var(--m-panel)] px-4 py-2.5 text-sm font-semibold hover:bg-[var(--m-accent)] transition-colors"
            >
              Open the free calendar
            </Link>
            <Link
              href="/brief"
              className="inline-flex rounded-md border border-[var(--m-line)] bg-[var(--m-panel)] px-4 py-2.5 text-sm font-medium text-[var(--m-ink)] hover:border-[var(--m-accent)] transition-colors"
            >
              See the morning brief
            </Link>
          </div>
        </div>

        {/* Asymmetric product frame — bleeds right, not a centered card stack */}
        <div className="m-settle-delay-2 pl-5 sm:pl-6 md:pl-[max(1.25rem,calc((100%-64rem)/2+1.25rem))] pb-16">
          <div className="rounded-tl-xl border border-[var(--m-line)] border-r-0 bg-[#0a0e17] text-[#e8edf7] shadow-[0_24px_60px_-28px_rgba(20,24,31,0.55)] overflow-hidden max-w-3xl">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[#243049] text-[11px] text-[#8a97b1]">
              <span className="text-[#5b8cff]">Calendar</span>
              <span>·</span>
              <span>implied move · timing · themes</span>
            </div>
            <div className="p-4 sm:p-5 space-y-3 font-mono text-sm">
              <div className="flex justify-between gap-4 border-b border-[#243049] pb-3">
                <div>
                  <div className="text-base font-semibold tracking-tight">NVDA</div>
                  <div className="text-[#8a97b1] text-xs mt-0.5">Wed · AMC</div>
                </div>
                <div className="text-right">
                  <div className="text-[#5b8cff] tabular">~7%</div>
                  <div className="text-[#8a97b1] text-xs">implied</div>
                </div>
              </div>
              <div className="flex justify-between gap-4 border-b border-[#243049] pb-3 opacity-80">
                <div>
                  <div className="text-base font-semibold tracking-tight">CRM</div>
                  <div className="text-[#8a97b1] text-xs mt-0.5">Thu · AMC</div>
                </div>
                <div className="text-right">
                  <div className="tabular">~5%</div>
                  <div className="text-[#8a97b1] text-xs">implied</div>
                </div>
              </div>
              <div className="flex justify-between gap-4 opacity-60">
                <div>
                  <div className="text-base font-semibold tracking-tight">AMD</div>
                  <div className="text-[#8a97b1] text-xs mt-0.5">Fri · BMO</div>
                </div>
                <div className="text-right">
                  <div className="tabular">~6%</div>
                  <div className="text-[#8a97b1] text-xs">implied</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="border-t border-[var(--m-line)] bg-[var(--m-panel)]/70">
        <div className="mx-auto max-w-5xl px-5 sm:px-6 py-16 sm:py-20">
          <h2 className="m-display text-2xl sm:text-3xl text-[var(--m-ink)] max-w-lg">
            Two things. That&apos;s the product.
          </h2>
          <div className="mt-10 grid grid-cols-1 md:grid-cols-2 gap-10 md:gap-16">
            <div>
              <h3 className="text-lg font-semibold text-[var(--m-ink)]">Calendar — free</h3>
              <p className="mt-3 text-[var(--m-muted)] leading-relaxed">
                Upcoming prints with timing, market cap, themes, and the options-implied
                move. Filter the week. Click into a name. No account required to look.
              </p>
              <Link
                href="/calendar"
                className="inline-block mt-4 text-[var(--m-accent)] font-medium m-link-underline"
              >
                Go to calendar
              </Link>
            </div>
            <div className="md:pt-8">
              <h3 className="text-lg font-semibold text-[var(--m-ink)]">
                Morning brief — Pro, $9.99/mo
              </h3>
              <p className="mt-3 text-[var(--m-muted)] leading-relaxed">
                One ranked focus for the session: what to do, what to watch, and the
                drop-if that kills the lean. Sample sizes and win rates stay visible so
                thin history doesn&apos;t get dressed up.
              </p>
              <Link
                href="/pricing"
                className="inline-block mt-4 text-[var(--m-accent)] font-medium m-link-underline"
              >
                Pricing
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-5 sm:px-6 py-16 sm:py-20">
        <h2 className="m-display text-2xl sm:text-3xl text-[var(--m-ink)]">
          How you actually use it
        </h2>
        <div className="mt-8 max-w-2xl space-y-8 text-[var(--m-muted)] leading-relaxed">
          <p>
            <span className="text-[var(--m-ink)] font-medium">Start on the calendar.</span>{" "}
            See who reports and what&apos;s already in the price. That part stays free
            because it should — you need a map before a lean.
          </p>
          <p>
            <span className="text-[var(--m-ink)] font-medium">Open the brief when you want a pick.</span>{" "}
            Pro ranks a focus from the same research stack (peer waves, post-earnings
            drift). You get a short board underneath, not a second product to learn.
          </p>
          <p>
            <span className="text-[var(--m-ink)] font-medium">Respect the kill switch.</span>{" "}
            Every setup carries a drop-if. If that prints, you&apos;re done — no hero
            holding through a broken thesis.
          </p>
        </div>
        <Link
          href="/how-it-works"
          className="inline-block mt-8 text-[var(--m-accent)] font-medium m-link-underline"
        >
          Longer walkthrough
        </Link>
      </section>

      <section className="border-t border-[var(--m-line)]">
        <div className="mx-auto max-w-5xl px-5 sm:px-6 py-16 sm:py-20 md:flex md:items-start md:gap-16">
          <h2 className="m-display text-2xl sm:text-3xl text-[var(--m-ink)] shrink-0 md:w-56">
            Who this is for
          </h2>
          <p className="mt-4 md:mt-1 text-[var(--m-muted)] leading-relaxed max-w-xl text-base sm:text-lg">
            People who already trade around earnings and are tired of scrolling five
            tabs to answer one question. If you want a firehose of alerts or a black-box
            “AI edge,” this isn&apos;t that. If you want a calendar that&apos;s honest
            about what&apos;s priced in — and, when you pay, one focus with a kill switch —
            it is.
          </p>
        </div>
      </section>

      <section className="border-t border-[var(--m-line)] bg-[var(--m-ink)] text-[var(--m-panel)]">
        <div className="mx-auto max-w-5xl px-5 sm:px-6 py-14 sm:py-16">
          <h2 className="m-display text-2xl sm:text-3xl">Pricing</h2>
          <ul className="mt-6 space-y-3 text-base text-[#c5ccd6] max-w-lg">
            <li>
              <span className="text-white font-medium">Free</span> — full earnings
              calendar, implied moves, company pages you can browse.
            </li>
            <li>
              <span className="text-white font-medium">Pro · $9.99/mo</span> — morning
              brief with focus setup, watch, and drop-if.
            </li>
          </ul>
          <Link
            href="/pricing"
            className="inline-flex mt-8 rounded-md bg-[var(--m-panel)] text-[var(--m-ink)] px-4 py-2.5 text-sm font-semibold hover:bg-[var(--m-accent-soft)] transition-colors"
          >
            Subscribe or manage billing
          </Link>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-5 sm:px-6 py-12">
        <p className="text-sm text-[var(--m-muted)] max-w-2xl leading-relaxed">
          For research and education only. Not financial advice. Markets move; data from
          Financial Modeling Prep and Yahoo Finance can be delayed or wrong. Options-implied
          moves are ATM-straddle estimates.
        </p>
      </section>
    </>
  );
}
