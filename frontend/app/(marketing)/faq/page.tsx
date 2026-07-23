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
    a: "A research site for earnings season. The free calendar shows who reports and what options markets have roughly priced in. Pro adds a morning brief with one focus setup — action, watch, and drop-if.",
  },
  {
    q: "What is free vs paid?",
    a: "The earnings calendar and browsing company context stay free. The morning brief (ranked focus setup with action / watch / drop-if) is Pro at $9.99 per month.",
  },
  {
    q: "What is the morning brief?",
    a: "A short daily page: today’s focus lean, a small board of other ranked setups, what changed since the last refresh, and who is printing today. Built so you are not scrolling Waves and Drift boards yourself.",
  },
  {
    q: "Do you give trade signals or financial advice?",
    a: "No. This is research and education only — not advice, not a recommendation to buy or sell anything. You own your decisions.",
  },
  {
    q: "Where does the data come from?",
    a: "Primarily Financial Modeling Prep and Yahoo Finance. Options-implied moves are estimates from ATM straddles and can be wrong or delayed.",
  },
  {
    q: "What are peer waves and post-earnings drift?",
    a: "Peer waves: a related company already reported and history suggests how names in the same theme have moved into their own prints. Drift: after a print, some stocks historically keep moving for a few sessions — we surface those patterns with sample honesty.",
  },
  {
    q: "How do I cancel Pro?",
    a: "Sign in, open Account (or Pricing), and use Manage / cancel — that opens Stripe’s billing portal.",
  },
  {
    q: "Is there an API or mobile app?",
    a: "Not as a public product yet. The website is the product.",
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

      <h1 className="m-display text-3xl sm:text-4xl text-[var(--m-ink)] tracking-tight">
        FAQ
      </h1>
      <p className="mt-4 text-[var(--m-muted)] leading-relaxed">
        Straight answers. If something here is wrong after a product change, email from
        Account or just yell into the void and we&apos;ll fix the page.
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
        Still curious?{" "}
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
