import type { Metadata } from "next";
import { ContactForm } from "@/components/marketing/ContactForm";

export const metadata: Metadata = {
  title: "Contact",
  description:
    "Email the earningsfollower team with product, billing, or data questions.",
  alternates: { canonical: "https://www.earningsfollower.com/contact" },
};

export default function ContactPage() {
  return (
    <article className="mx-auto max-w-xl px-5 sm:px-6 py-14 sm:py-20">
      <h1 className="m-display m-hero-brand text-3xl sm:text-4xl text-[var(--m-ink)] tracking-tight">
        Contact
      </h1>
      <p className="m-hero-line mt-4 text-[var(--m-muted)] leading-relaxed">
        Questions about the product, billing, or data? Send a note — replies go to
        the email you enter.
      </p>
      <ContactForm />
    </article>
  );
}
