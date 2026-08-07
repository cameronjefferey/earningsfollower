"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { usePathname } from "next/navigation";

/** Sign in / Sign up / Account for the marketing chrome. */
export function MarketingAuth({
  variant = "nav",
}: {
  variant?: "nav" | "footer";
}) {
  const { data: session, status } = useSession();
  const pathname = usePathname();
  const next = encodeURIComponent(pathname || "/");
  const loginHref = `/login?next=${next}`;
  const signupHref = `/login?mode=signup&next=${next}`;

  if (status === "loading") {
    if (variant === "footer") {
      return <span className="text-[var(--m-muted)]">…</span>;
    }
    return (
      <span className="m-nav-link opacity-50" aria-hidden>
        …
      </span>
    );
  }

  if (!session) {
    if (variant === "footer") {
      return (
        <>
          <Link href={signupHref} className="hover:text-white transition-colors">
            Sign up
          </Link>
          <Link href={loginHref} className="hover:text-white transition-colors">
            Sign in
          </Link>
        </>
      );
    }
    return (
      <>
        <Link href={loginHref} className="m-nav-link">
          Sign in
        </Link>
        <Link href={signupHref} className="m-nav-cta">
          Sign up
        </Link>
      </>
    );
  }

  const label = session.user?.name?.split(" ")[0] || "Account";

  if (variant === "footer") {
    return (
      <Link href="/account" className="hover:text-white transition-colors">
        Account
      </Link>
    );
  }

  return (
    <Link
      href="/account"
      className="m-nav-link inline-flex items-center gap-1.5 max-w-[8rem]"
      title={session.user?.email ?? "Account"}
    >
      {session.user?.image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={session.user.image}
          alt=""
          className="h-4 w-4 rounded-full"
          referrerPolicy="no-referrer"
        />
      ) : null}
      <span className="truncate">{label}</span>
    </Link>
  );
}
