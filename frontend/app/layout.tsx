import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono } from "next/font/google";
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

export const metadata: Metadata = {
  metadataBase: new URL("https://www.earningsfollower.com"),
  title: {
    default: "earningsfollower | earnings calendar & trading boards",
    template: "%s · earningsfollower",
  },
  description:
    "Free earnings calendar with implied moves, plus Pro Drift and Waves boards for post-earnings continuation and peer-wave setups.",
  openGraph: {
    type: "website",
    siteName: "earningsfollower",
    title: "earningsfollower | earnings calendar & trading boards",
    description:
      "Who reports, what's priced in, and the live boards to trade from. Free calendar; Pro Drift + Waves.",
    url: "https://www.earningsfollower.com",
  },
  twitter: {
    card: "summary_large_image",
    title: "earningsfollower | earnings calendar & trading boards",
    description:
      "Who reports, what's priced in, and the live boards to trade from. Free calendar; Pro Drift + Waves.",
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
      className={`${sans.variable} ${mono.variable}`}
    >
      <body className="antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
