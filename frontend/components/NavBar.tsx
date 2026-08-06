"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AuthMenu } from "@/components/AuthMenu";

/** Product nav: Calendar + Boards. Drift/Waves live under Boards. */
const links = [
  { href: "/calendar", label: "Calendar" },
  { href: "/boards?tab=waves", label: "Boards" },
];

export function NavBar() {
  const pathname = usePathname();

  return (
    <nav className="flex items-center gap-1">
      {links.map((l) => {
        const active =
          l.href === "/calendar"
            ? pathname === "/calendar" || pathname.startsWith("/calendar/")
            : pathname.startsWith("/boards") ||
              pathname.startsWith("/drift") ||
              pathname.startsWith("/waves");
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
