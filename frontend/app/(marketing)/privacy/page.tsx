import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "Privacy Policy for earningsfollower.",
  alternates: { canonical: "https://www.earningsfollower.com/privacy" },
};

export default function PrivacyPage() {
  return (
    <article className="mx-auto max-w-2xl px-5 sm:px-6 py-14 sm:py-20">
      <h1 className="m-display m-hero-brand text-3xl sm:text-4xl text-[var(--m-ink)] tracking-tight">
        Privacy Policy
      </h1>
      <p className="mt-4 text-sm text-[var(--m-muted)]">Last updated: August 7, 2026</p>

      <div className="mt-10 space-y-8 text-[var(--m-muted)] leading-relaxed">
        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Overview</h2>
          <p>
            This policy explains what we collect when you use earningsfollower, how we
            use it, and the choices you have. We aim to collect only what we need to run
            the product and bill subscriptions.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Information we collect</h2>
          <ul className="list-disc pl-5 space-y-2">
            <li>
              <span className="text-[var(--m-ink)]">Account data</span> — email, name,
              profile image (if you sign in with Google), and password hash if you create
              an email/password account.
            </li>
            <li>
              <span className="text-[var(--m-ink)]">Billing data</span> — handled by
              Stripe. We store Stripe customer/subscription ids and subscription status;
              we do not store full card numbers.
            </li>
            <li>
              <span className="text-[var(--m-ink)]">Messages</span> — if you use Contact,
              we receive the name, email, and message you submit.
            </li>
            <li>
              <span className="text-[var(--m-ink)]">Usage & logs</span> — standard server
              logs (IP, user agent, paths) for security, rate limiting, and debugging.
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">How we use information</h2>
          <ul className="list-disc pl-5 space-y-2">
            <li>Provide sign-in, sessions, and paid feature access</li>
            <li>Process subscriptions and send transactional email (magic links, resets)</li>
            <li>Respond to contact messages</li>
            <li>Monitor abuse, outages, and billing failures</li>
            <li>Improve the product</li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Processors</h2>
          <p>We use third parties to operate the Service, including:</p>
          <ul className="list-disc pl-5 space-y-2">
            <li>Stripe — payments</li>
            <li>Resend — transactional and contact email</li>
            <li>Google — optional OAuth sign-in</li>
            <li>Render — hosting and database</li>
            <li>Reddit — advertising measurement (conversion pixel) when ads are running</li>
            <li>Market data providers (e.g. FMP, Yahoo) — market/earnings data (not your personal account content)</li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Cookies & auth</h2>
          <p>
            We use session cookies (and related auth storage) so you stay signed in. When
            we run Reddit ads, the Reddit Pixel may set cookies or similar identifiers to
            measure visits and conversions (for example sign-ups and purchases) and help
            us optimize campaigns. See{" "}
            <a
              href="https://www.reddit.com/policies/privacy-policy"
              className="text-[var(--m-accent)] hover:underline"
              target="_blank"
              rel="noreferrer"
            >
              Reddit&apos;s privacy policy
            </a>
            .
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Retention</h2>
          <p>
            We keep account and billing records while your account is active and as needed
            for legal, tax, and fraud prevention. You can request deletion of your account
            data via{" "}
            <Link href="/contact" className="text-[var(--m-accent)] hover:underline">
              Contact
            </Link>
            ; we may retain limited records required for compliance.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Your choices</h2>
          <ul className="list-disc pl-5 space-y-2">
            <li>Update profile details in Account where available</li>
            <li>Cancel a subscription in Account → billing portal</li>
            <li>Request access or deletion via Contact</li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Children</h2>
          <p>
            The Service is not directed to children under 13, and we do not knowingly
            collect their personal information.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Changes</h2>
          <p>
            We may update this policy. The “Last updated” date will change when we do.
            Continued use means you accept the updated policy.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="m-display text-xl text-[var(--m-ink)]">Contact</h2>
          <p>
            Privacy questions:{" "}
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
