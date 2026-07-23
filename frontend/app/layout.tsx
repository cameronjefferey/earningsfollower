import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono, Literata, Source_Sans_3 } from "next/font/google";
import "./globals.css";
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

const marketingDisplay = Literata({
  subsets: ["latin"],
  variable: "--font-marketing-display",
  display: "swap",
});

const marketingSans = Source_Sans_3({
  subsets: ["latin"],
  variable: "--font-marketing-sans",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://www.earningsfollower.com"),
  title: {
    default: "earningsfollower — earnings calendar & morning brief",
    template: "%s · earningsfollower",
  },
  description:
    "Free earnings calendar with implied moves, plus a Pro morning brief that names one focus setup — action, watch, and when to drop it.",
  openGraph: {
    type: "website",
    siteName: "earningsfollower",
    title: "earningsfollower — earnings calendar & morning brief",
    description:
      "Who prints, what's priced in, and what to lean on. Free calendar; Pro morning brief.",
    url: "https://www.earningsfollower.com",
  },
  twitter: {
    card: "summary_large_image",
    title: "earningsfollower — earnings calendar & morning brief",
    description:
      "Who prints, what's priced in, and what to lean on. Free calendar; Pro morning brief.",
  },
  alternates: {
    canonical: "https://www.earningsfollower.com",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${sans.variable} ${mono.variable} ${marketingDisplay.variable} ${marketingSans.variable}`}
    >
      <body className="antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
