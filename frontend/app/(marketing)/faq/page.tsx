import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "FAQ",
  description:
    "FAQ for earningsfollower: free earnings calendar vs Pro morning brief, pricing, data sources, and what the product is not.",
  alternates: { canonical: "https://www.earningsfollower.com/faq" },
};

const faqs: { q: string; a: string }[] = [
  {
    q: "What is earningsfollower?",
    a: "Research for earnings season built around what’s already priced in options, peer waves and post-report drift, and one morning focus with action / watch / drop-if.",
  },
  {
    q: "What’s free vs paid?",
    a: "Calendar and company pages stay free. The morning brief (ranked focus + short board) is Pro — details on Pricing.",
  },
  {
    q: "What’s on the morning brief?",
    a: "One focus lean for the session (usually a peer wave or post-report drift), a short ranked board, what changed since the last refresh, and who’s reporting today.",
  },
  {
    q: "Is this financial advice or trade signals?",
    a: "No. Research and education only. You decide what to do.",
  },
  {
    q: "Where does the data come from?",
    a: "Mostly Financial Modeling Prep and Yahoo Finance. Implied moves are ATM-straddle estimates and can be wrong or delayed.",
  },
  {
    q: "Peer waves and post-earnings drift?",
    a: "Peer waves: a related company already reported; we look at how names in that theme have moved into their own reports. Drift: after a report, some stocks historically keep moving for a few sessions — we show that with sample size attached.",
  },
  {
    q: "How do I cancel?",
    a: "Account or Pricing → Manage / cancel. That opens Stripe’s billing portal.",
  },
  {
    q: "API or mobile app?",
    a: "Not publicly. The site is the product.",
  },
];

export default function FaqPage() {
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: {
        "@type": "Answer",
        text: f.a,
      },
    })),
  };

  return (
    <article className="mx-auto max-w-2xl px-5 sm:px-6 py-14 sm:py-20">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <h1 className="m-display m-hero-brand text-3xl sm:text-4xl text-[var(--m-ink)] tracking-tight">
        FAQ
      </h1>
      <p className="m-hero-line mt-4 text-[var(--m-muted)] leading-relaxed">
        Short answers. If something drifts out of date, tell us from Account.
      </p>

      <dl className="mt-12 space-y-10">
        {faqs.map((f) => (
          <div key={f.q}>
            <dt className="m-display text-xl text-[var(--m-ink)]">{f.q}</dt>
            <dd className="mt-2 text-[var(--m-muted)] leading-relaxed">{f.a}</dd>
          </div>
        ))}
      </dl>

      <p className="mt-14 text-sm text-[var(--m-muted)]">
        <Link href="/how-it-works" className="text-[var(--m-accent)] m-link-underline">
          How it works
        </Link>
        {" · "}
        <Link href="/calendar" className="text-[var(--m-accent)] m-link-underline">
          Calendar
        </Link>
        {" · "}
        <Link href="/pricing" className="text-[var(--m-accent)] m-link-underline">
          Pricing
        </Link>
      </p>
    </article>
  );
}
