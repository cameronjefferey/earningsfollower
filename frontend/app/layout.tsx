import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import { NavBar } from "@/components/NavBar";
import { Providers } from "@/components/Providers";

const sans = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-instrument",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "earningsfollower",
  description:
    "Earnings calendar and morning brief — who prints, what's priced in, and what to lean on.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body className="antialiased">
        <Providers>
          <div className="min-h-screen flex flex-col">
            <header className="border-b border-[var(--color-edge)]/80 bg-[var(--color-ink)]/80 backdrop-blur-md sticky top-0 z-20">
              <div className="mx-auto max-w-6xl px-4 sm:px-5 py-3.5 flex items-center justify-between gap-4">
                <Link href="/" className="flex items-center gap-2 shrink-0">
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
              <div className="mx-auto max-w-6xl px-4 sm:px-5 text-xs text-[var(--color-muted)] leading-relaxed">
                For research and educational purposes only. Not financial advice. Data via
                Financial Modeling Prep and Yahoo Finance; may be delayed or inaccurate.
                Options-implied moves are estimates from ATM straddles.
              </div>
            </footer>
          </div>
        </Providers>
      </body>
    </html>
  );
}
