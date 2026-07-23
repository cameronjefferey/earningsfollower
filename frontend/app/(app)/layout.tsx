import Link from "next/link";
import { NavBar } from "@/components/NavBar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-[var(--color-ink)] text-[#e8edf7]">
      <header className="border-b border-[var(--color-edge)]/80 bg-[var(--color-ink)]/80 backdrop-blur-md sticky top-0 z-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 py-3.5 flex items-center justify-between gap-4">
          <Link href="/calendar" className="flex items-center gap-2 shrink-0">
            <span className="text-lg sm:text-xl font-semibold tracking-tight">
              earnings
              <span className="text-[var(--color-accent)]">follower</span>
            </span>
          </Link>
          <NavBar />
        </div>
      </header>

      <main className="flex-1 mx-auto max-w-6xl w-full px-4 sm:px-5 py-8">
        {children}
      </main>

      <footer className="border-t border-[var(--color-edge)]/80 py-5">
        <div className="mx-auto max-w-6xl px-4 sm:px-5 text-xs text-[var(--color-muted)] leading-relaxed flex flex-wrap gap-x-4 gap-y-1">
          <span>
            For research and educational purposes only. Not financial advice. Data via
            Financial Modeling Prep and Yahoo Finance; may be delayed or inaccurate.
            Options-implied moves are estimates from ATM straddles.
          </span>
          <Link href="/" className="text-[var(--color-accent)] hover:underline shrink-0">
            About
          </Link>
        </div>
      </footer>
    </div>
  );
}
