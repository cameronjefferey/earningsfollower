"use client";

import Link from "next/link";
import { signIn, useSession } from "next-auth/react";
import { usePathname } from "next/navigation";

/** Sign in / Account for the marketing chrome. Google creates the account on first use. */
export function MarketingAuth({
  variant = "nav",
}: {
  variant?: "nav" | "footer";
}) {
  const { data: session, status } = useSession();
  const pathname = usePathname();

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
        <button
          type="button"
          onClick={() => signIn("google", { callbackUrl: pathname || "/" })}
          className="hover:text-white transition-colors text-left"
        >
          Sign in
        </button>
      );
    }
    return (
      <button
        type="button"
        onClick={() => signIn("google", { callbackUrl: pathname || "/" })}
        className="m-nav-link"
      >
        Sign in
      </button>
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
