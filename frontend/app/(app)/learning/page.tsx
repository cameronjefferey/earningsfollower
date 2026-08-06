"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  api,
  AttributionResponse,
  ExecutionResponse,
  NarrativeResponse,
  ProgressResponse,
} from "@/lib/api";
import { EmptyState, Spinner } from "@/components/ui";
import { useAuthReady } from "@/lib/useAuthReady";
import { WeeklyProgress } from "@/components/WeeklyProgress";
import { Narrative } from "@/components/Narrative";
import { Attribution } from "@/components/Attribution";
import { ExecutionQuality } from "@/components/ExecutionQuality";
import { LearningTakeaways } from "@/components/LearningTakeaways";

export default function LearningPage() {
  const [attribution, setAttribution] = useState<AttributionResponse | null>(null);
  const [narrative, setNarrative] = useState<NarrativeResponse | null>(null);
  const [progress, setProgress] = useState<ProgressResponse | null>(null);
  const [execution, setExecution] = useState<ExecutionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [showNumbers, setShowNumbers] = useState(false);

  const { ready, accessToken } = useAuthReady();

  useEffect(() => {
    if (!ready) return;
    setLoading(true);
    Promise.allSettled([
      api.paperProgress(8, accessToken).then(setProgress),
      api.paperNarrative(accessToken).then(setNarrative),
      api.paperAttribution(5, accessToken).then(setAttribution),
      api.paperExecution(5, 8, accessToken).then(setExecution),
    ]).then((results) => {
      if (results.every((r) => r.status === "rejected")) setError(true);
      setLoading(false);
    });
  }, [ready, accessToken]);

  if (!ready || loading) return <Spinner label="Loading learning…" />;
  if (error) return <EmptyState title="Couldn't load the learning data." />;

  const hasProgress = Boolean(
    progress?.weeks.some(
      (w) => w.cumulative.graded_trades > 0 || w.new_this_week.closed > 0
    )
  );
  const hasNarrative = Boolean(narrative && narrative.source !== "empty");
  const hasAttribution = Boolean(attribution && attribution.graded_trades > 0);
  const hasExecution = Boolean(execution && execution.graded_signals > 0);
  const hasAnyData = hasProgress || hasNarrative || hasAttribution || hasExecution;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Learning</h1>
        <p className="text-[var(--color-muted)] mt-1 max-w-2xl leading-relaxed">
          What the paper trader is learning from closed trades — and how you can
          use the same lessons in your own book. Live positions stay on{" "}
          <Link href="/paper" className="text-[var(--color-accent)] hover:underline">
            Paper
          </Link>
          .
        </p>
      </div>

      {hasAnyData ? (
        <>
          <LearningTakeaways
            narrative={narrative}
            progress={progress}
            attribution={attribution}
            execution={execution}
          />
          <Narrative report={narrative} />
          <WeeklyProgress report={progress} />

          <div className="mb-8">
            <button
              type="button"
              onClick={() => setShowNumbers((v) => !v)}
              className="text-sm text-[var(--color-accent)] hover:underline"
            >
              {showNumbers ? "Hide the detailed numbers ↑" : "Show the detailed numbers ↓"}
            </button>
            {showNumbers ? (
              <div className="mt-4 space-y-2">
                <p className="text-xs text-[var(--color-muted)] mb-4 max-w-2xl">
                  Optional deep dive: signal quality, entry/exit timing, and which
                  cohorts win. You don&apos;t need this section to act on the
                  takeaways above.
                </p>
                <ExecutionQuality report={execution} />
                <Attribution report={attribution} />
              </div>
            ) : null}
          </div>
        </>
      ) : (
        <EmptyState
          title="Nothing graded yet."
          hint="Once paper trades close, this page will spell out what worked, what didn't, and what to try in your own trades. Check Paper for live positions in the meantime."
        />
      )}
    </div>
  );
}
