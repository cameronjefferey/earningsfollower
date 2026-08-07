import Link from "next/link";
import { MarketingAuth } from "@/components/marketing/MarketingAuth";

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="marketing">
      <header className="m-nav">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-3.5 flex items-center justify-between gap-4">
          <Link href="/" className="m-brand">
            earnings<span>follower</span>
          </Link>
          <nav className="flex items-center gap-1 sm:gap-2 text-sm">
            <Link href="/how-it-works" className="m-nav-link hidden sm:inline">
              How it works
            </Link>
            <Link href="/faq" className="m-nav-link hidden sm:inline">
              FAQ
            </Link>
            <Link href="/contact" className="m-nav-link hidden md:inline">
              Contact
            </Link>
            <Link href="/pricing" className="m-nav-link">
              Pricing
            </Link>
            <MarketingAuth />
            <Link href="/calendar" className="m-nav-cta">
              Launch calendar
            </Link>
          </nav>
        </div>
      </header>

      <main>{children}</main>

      <footer className="border-t border-[var(--m-line)] mt-8">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-10 flex flex-col sm:flex-row gap-6 sm:justify-between text-sm text-[var(--m-muted)]">
          <div className="max-w-md space-y-2">
            <p className="m-brand text-base">
              earnings<span>follower</span>
            </p>
            <p>
              Priced-in map, post-report drift, peer waves. Not a signal service. Not
              advice. Numbers can be late or wrong.
            </p>
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-2 sm:flex-col sm:items-end">
            <Link href="/calendar" className="hover:text-white transition-colors">
              Calendar
            </Link>
            <Link href="/boards" className="hover:text-white transition-colors">
              Boards
            </Link>
            <Link href="/pricing" className="hover:text-white transition-colors">
              Pricing
            </Link>
            <MarketingAuth variant="footer" />
            <Link href="/faq" className="hover:text-white transition-colors">
              FAQ
            </Link>
            <Link href="/contact" className="hover:text-white transition-colors">
              Contact
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
