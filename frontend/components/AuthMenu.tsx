"use client";

import Link from "next/link";
import { signIn, useSession } from "next-auth/react";
import { usePathname } from "next/navigation";

function NavLink({
  href,
  label,
  active,
}: {
  href: string;
  label: string;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
        active
          ? "bg-[var(--color-accent)]/15 text-[var(--color-accent)]"
          : "text-[var(--color-muted)] hover:text-white hover:bg-[var(--color-panel-2)]"
      }`}
    >
      {label}
    </Link>
  );
}

export function AuthMenu() {
  const { data: session, status } = useSession();
  const pathname = usePathname();

  if (status === "loading") {
    return (
      <span className="px-3 py-1.5 text-sm text-[var(--color-muted)]">…</span>
    );
  }

  if (!session) {
    return (
      <div className="flex items-center gap-1 ml-1 pl-1 border-l border-[var(--color-edge)]">
        <NavLink
          href="/pricing"
          label="Pricing"
          active={pathname.startsWith("/pricing")}
        />
        <button
          type="button"
          onClick={() => signIn("google", { callbackUrl: pathname || "/" })}
          className="px-3 py-1.5 rounded-lg text-sm font-medium bg-[var(--color-accent)]/15 text-[var(--color-accent)] hover:bg-[var(--color-accent)]/25"
        >
          Sign in
        </button>
      </div>
    );
  }

  const label = session.user?.name?.split(" ")[0] || "Account";

  return (
    <div className="flex items-center gap-1 ml-1 pl-1 border-l border-[var(--color-edge)]">
      {session.isAdmin ? (
        <>
          <NavLink
            href="/paper"
            label="Paper"
            active={pathname.startsWith("/paper")}
          />
          <NavLink
            href="/learning"
            label="Learning"
            active={pathname.startsWith("/learning")}
          />
        </>
      ) : null}
      <NavLink
        href="/pricing"
        label={session.subscribed ? "Pricing" : "Upgrade"}
        active={pathname.startsWith("/pricing")}
      />
      <Link
        href="/account"
        className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-sm font-medium transition-colors ${
          pathname.startsWith("/account")
            ? "bg-[var(--color-accent)]/15 text-[var(--color-accent)]"
            : "text-[var(--color-muted)] hover:text-white hover:bg-[var(--color-panel-2)]"
        }`}
        title={session.user?.email ?? "Account"}
      >
        {session.user?.image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={session.user.image}
            alt=""
            className="h-5 w-5 rounded-full"
            referrerPolicy="no-referrer"
          />
        ) : (
          <span className="h-5 w-5 rounded-full bg-[var(--color-panel-2)] border border-[var(--color-edge)] inline-flex items-center justify-center text-[10px]">
            {(session.user?.email?.[0] || "?").toUpperCase()}
          </span>
        )}
        <span className="hidden sm:inline max-w-[7rem] truncate">{label}</span>
      </Link>
    </div>
  );
}
