import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "Terms of Service for earningsfollower.",
  alternates: { canonical: "https://www.earningsfollower.com/terms" },
};

export default function TermsPage() {
  return (
    <article className="mx-auto max-w-2xl px-5 sm:px-6 py-14 sm:py-20 prose-invert">
      <h1 className="m-display m-hero-brand text-3xl sm:text-4xl text-[var(--m-ink)] tracking-tight">
        Terms of Service
      </h1>
      <p className="mt-4 text-sm text-[var(--m-muted)]">Last updated: August 7, 2026</p>

      <div className="mt-10 space-y-8 text-[var(--m-muted)] leading-relaxed">
        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Agreement</h2>
          <p>
            By using earningsfollower (the “Service”), you agree to these Terms. If you
            do not agree, do not use the Service.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">What this is</h2>
          <p>
            The Service provides research and educational tools related to earnings
            calendars, options-implied moves, and related market data. It is{" "}
            <strong className="text-[var(--m-ink)]">not</strong> financial, investment,
            tax, or trading advice, and it is not a broker or signal service. You are
            solely responsible for any decisions you make.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Accounts</h2>
          <p>
            You must provide accurate account information and keep your login credentials
            secure. You are responsible for activity under your account. We may suspend
            or terminate accounts that abuse the Service or violate these Terms.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Subscriptions & billing</h2>
          <p>
            Paid features are billed through Stripe on the plan shown at checkout.
            Subscriptions renew until canceled. You can manage or cancel billing in your
            Account (Stripe Customer Portal). Fees are generally non-refundable except
            where required by law or expressly offered by us.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Data accuracy</h2>
          <p>
            Market and earnings data may be delayed, incomplete, or wrong. Implied-move
            estimates are approximations. Do not rely on the Service as your only source
            of truth before trading or investing.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Acceptable use</h2>
          <p>
            Do not scrape, resell, or redistribute the Service in bulk; attempt to bypass
            paywalls or rate limits; interfere with the Service; or use it for unlawful
            activity. We may rate-limit or block abusive traffic.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Intellectual property</h2>
          <p>
            The Service, branding, and original content are owned by us or our licensors.
            You receive a limited, non-exclusive license to use the Service for your own
            research while your account is in good standing.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Disclaimer of warranties</h2>
          <p>
            THE SERVICE IS PROVIDED “AS IS” AND “AS AVAILABLE” WITHOUT WARRANTIES OF ANY
            KIND, EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR
            PURPOSE, AND NON-INFRINGEMENT.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Limitation of liability</h2>
          <p>
            TO THE MAXIMUM EXTENT PERMITTED BY LAW, WE ARE NOT LIABLE FOR INDIRECT,
            INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR TRADING LOSSES, OR FOR LOST PROFITS,
            DATA, OR GOODWILL. OUR TOTAL LIABILITY FOR CLAIMS RELATED TO THE SERVICE IS
            LIMITED TO THE AMOUNT YOU PAID US IN THE THREE MONTHS BEFORE THE CLAIM.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Changes</h2>
          <p>
            We may update these Terms or the Service. Material changes will be reflected
            by updating the date above. Continued use after changes means you accept the
            updated Terms.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Contact</h2>
          <p>
            Questions about these Terms:{" "}
            <Link href="/contact" className="text-[var(--m-accent)] hover:underline">
              Contact
            </Link>
            .
          </p>
        </section>
      </div>
    </article>
  );
}
