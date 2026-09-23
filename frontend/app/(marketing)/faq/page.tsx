import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "FAQ",
  description:
    "FAQ for earningsfollower: free $10B+ earnings calendar, peer waves, and 5-day losers.",
  alternates: { canonical: "https://www.earningsfollower.com/faq" },
};

const faqs: { q: string; a: string }[] = [
  {
    q: "What is earningsfollower?",
    a: "Research for earnings season on large caps: what’s already priced in options, peer waves into the next report, and the week’s worst 5-day losers.",
  },
  {
    q: "What’s free vs paid?",
    a: "The earnings calendar is free with no account, and it only lists $10B+ names (application software is left off). Company pages are free too: a few pages as a guest, unlimited with a free account. The live Waves board is Pro. The 5-day losers list is on the boards page. Details on Pricing.",
  },
  {
    q: "What’s on the boards?",
    a: "Waves: large-cap names reporting next, after at least two peers in the theme already ripped. 5-day losers: the worst five-session S&P names, the same list the book ranks each week.",
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
    q: "Peer waves and 5-day losers?",
    a: "Peer waves: a related large-cap already reported and ripped; we look at how names in that theme have moved into their own reports. 5-day losers: the worst five-session drops in the S&P 500, with names that report too soon left off.",
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
        Short answers. Still stuck?{" "}
        <Link href="/contact" className="text-[var(--m-ink)] underline underline-offset-2">
          Send a question
        </Link>
        .
      </p>

      <dl className="mt-12 space-y-10">
        {faqs.map((f) => (
          <div key={f.q}>
            <dt className="m-display text-xl text-[var(--m-ink)]">{f.q}</dt>
            <dd className="mt-2 text-[var(--m-muted)] leading-relaxed">{f.a}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-14 flex flex-wrap gap-3">
        <Link href="/calendar" className="m-btn-primary">
          Open calendar
        </Link>
        <Link href="/contact" className="m-btn-ghost">
          Contact
        </Link>
        <Link href="/boards" className="m-btn-ghost">
          Boards
        </Link>
      </div>
    </article>
  );
}
