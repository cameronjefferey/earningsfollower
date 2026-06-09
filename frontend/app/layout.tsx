import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { NavBar } from "@/components/NavBar";

export const metadata: Metadata = {
  title: "earningsfollower",
  description: "Trade smarter around earnings: calendar, reaction stats, implied moves, and peer waves.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen flex flex-col">
          <header className="border-b border-[var(--color-edge)] bg-[var(--color-panel)]/60 backdrop-blur sticky top-0 z-20">
            <div className="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between">
              <Link href="/" className="flex items-center gap-2">
                <span className="text-xl font-bold tracking-tight">
                  earnings<span className="text-[var(--color-accent)]">follower</span>
                </span>
              </Link>
              <NavBar />
            </div>
          </header>

          <main className="flex-1 mx-auto max-w-6xl w-full px-4 py-6">{children}</main>

          <footer className="border-t border-[var(--color-edge)] py-4">
            <div className="mx-auto max-w-6xl px-4 text-xs text-[var(--color-muted)]">
              For research and educational purposes only. Not financial advice. Data via
              Financial Modeling Prep and Yahoo Finance; may be delayed or inaccurate.
              Options-implied moves are estimates from ATM straddles.
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
