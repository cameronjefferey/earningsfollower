"use client";

import { Suspense, useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { DriftBoard } from "@/components/boards/DriftBoard";
import { WavesBoard } from "@/components/boards/WavesBoard";
import { Spinner } from "@/components/ui";

type BoardTab = "drift" | "waves";

function parseTab(value: string | null): BoardTab {
  return value === "drift" ? "drift" : "waves";
}

function BoardsInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const tab = parseTab(searchParams.get("tab"));

  const setTab = useCallback(
    (next: BoardTab) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", next);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Boards</h1>
          <p className="text-sm text-[var(--color-muted)] mt-1 max-w-2xl">
            Live peer-wave and post-earnings drift setups - the boards you trade from.
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-[var(--color-edge)] p-0.5">
          {(
            [
              { key: "waves", label: "Waves" },
              { key: "drift", label: "Drift" },
            ] as const
          ).map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`px-3.5 py-1.5 rounded-md text-sm font-medium transition-colors ${
                tab === t.key
                  ? "bg-[var(--color-accent)]/15 text-[var(--color-accent)]"
                  : "text-[var(--color-muted)] hover:text-white"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "waves" ? (
        <WavesBoard embedded />
      ) : (
        <DriftBoard embedded />
      )}
    </div>
  );
}

export default function BoardsPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <BoardsInner />
    </Suspense>
  );
}
