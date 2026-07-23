"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AuthMenu } from "@/components/AuthMenu";

/** Product nav stays tiny on purpose — Calendar + Brief. Boards link from the brief. */
const links = [
  { href: "/", label: "Calendar" },
  { href: "/brief", label: "Brief" },
];

export function NavBar() {
  const pathname = usePathname();

  return (
    <nav className="flex items-center gap-1">
      {links.map((l) => {
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
