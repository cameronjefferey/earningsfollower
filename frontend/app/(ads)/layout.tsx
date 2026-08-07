import Link from "next/link";

/** Lean chrome for paid-traffic landings — brand + sign-in only. */
export default function AdsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="marketing">
      <header className="m-nav">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-3.5 flex items-center justify-between gap-4">
          <Link href="/" className="m-brand">
            earnings<span>follower</span>
          </Link>
          <Link href="/login" className="m-nav-link">
            Sign in
          </Link>
        </div>
      </header>
      <main>{children}</main>
      <footer className="border-t border-[var(--m-line)] py-6">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 flex flex-wrap gap-x-5 gap-y-2 text-xs text-[var(--m-muted)]">
          <span>Research only. Not financial advice.</span>
          <Link href="/terms" className="hover:text-white">
            Terms
          </Link>
          <Link href="/privacy" className="hover:text-white">
            Privacy
          </Link>
          <Link href="/contact" className="hover:text-white">
            Contact
          </Link>
        </div>
      </footer>
    </div>
  );
}
