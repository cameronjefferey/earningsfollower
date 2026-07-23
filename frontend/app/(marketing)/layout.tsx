import Link from "next/link";

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="marketing m-grain">
      <header className="border-b border-[var(--m-line)]/80">
        <div className="mx-auto max-w-5xl px-5 sm:px-6 py-4 flex items-center justify-between gap-4">
          <Link
            href="/"
            className="m-display text-xl sm:text-2xl tracking-tight text-[var(--m-ink)]"
          >
            earningsfollower
          </Link>
          <nav className="flex items-center gap-4 sm:gap-5 text-sm text-[var(--m-muted)]">
            <Link href="/how-it-works" className="m-link-underline hover:text-[var(--m-ink)]">
              How it works
            </Link>
            <Link href="/faq" className="m-link-underline hover:text-[var(--m-ink)]">
              FAQ
            </Link>
            <Link
              href="/calendar"
              className="rounded-md bg-[var(--m-ink)] text-[var(--m-panel)] px-3 py-1.5 font-medium hover:bg-[var(--m-accent)] transition-colors"
            >
              Open calendar
            </Link>
          </nav>
        </div>
      </header>

      <main>{children}</main>

      <footer className="mt-20 border-t border-[var(--m-line)]">
        <div className="mx-auto max-w-5xl px-5 sm:px-6 py-10 flex flex-col sm:flex-row gap-6 sm:justify-between text-sm text-[var(--m-muted)]">
          <div className="max-w-md space-y-2">
            <p className="m-display text-[var(--m-ink)] text-lg">earningsfollower</p>
            <p>
              Research tool for earnings season — not a signal service, not financial
              advice. Numbers can be late or wrong.
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:items-end">
            <Link href="/calendar" className="m-link-underline hover:text-[var(--m-ink)]">
              Calendar
            </Link>
            <Link href="/brief" className="m-link-underline hover:text-[var(--m-ink)]">
              Morning brief
            </Link>
            <Link href="/pricing" className="m-link-underline hover:text-[var(--m-ink)]">
              Pricing
            </Link>
            <Link href="/faq" className="m-link-underline hover:text-[var(--m-ink)]">
              FAQ
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
