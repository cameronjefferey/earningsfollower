"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import { AuthMenu } from "@/components/AuthMenu";

const links = [
  { href: "/", label: "Calendar", adminOnly: false },
  { href: "/digest", label: "Digest", adminOnly: false },
  { href: "/waves", label: "Waves", adminOnly: false },
  { href: "/drift", label: "Drift", adminOnly: false },
  { href: "/reddit", label: "Reddit", adminOnly: false },
  { href: "/track-record", label: "Track record", adminOnly: false },
  { href: "/paper", label: "Paper", adminOnly: true },
  { href: "/learning", label: "Learning", adminOnly: true },
];

export function NavBar() {
  const pathname = usePathname();
  const { data: session } = useSession();
  const isAdmin = Boolean(session?.isAdmin);

  return (
    <nav className="flex items-center gap-1">
      {links
        .filter((l) => !l.adminOnly || isAdmin)
        .map((l) => {
          const active =
            l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
          return (
            <Link
              key={l.href}
              href={l.href}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                active
                  ? "bg-[var(--color-accent)]/15 text-[var(--color-accent)]"
                  : "text-[var(--color-muted)] hover:text-white hover:bg-[var(--color-panel-2)]"
              }`}
            >
              {l.label}
            </Link>
          );
        })}
      <AuthMenu />
    </nav>
  );
}
