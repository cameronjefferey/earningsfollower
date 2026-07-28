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

export default function LearningPage() {
  const [attribution, setAttribution] = useState<AttributionResponse | null>(null);
  const [narrative, setNarrative] = useState<NarrativeResponse | null>(null);
  const [progress, setProgress] = useState<ProgressResponse | null>(null);
  const [execution, setExecution] = useState<ExecutionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const { ready, accessToken } = useAuthReady();

  useEffect(() => {
    if (!ready) return;
    setLoading(true);
    // Each view loads independently; the page renders once all have settled so a
    // slow LLM narrative doesn't hold up the metrics.
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

  // With a fresh account nothing has graded yet: the progress table, the
  // narrative, and attribution all self-hide, which leaves the page looking
  // broken. Detect that and show one honest empty state instead of an orphan.
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
        <p className="text-[var(--color-muted)] mt-1 max-w-3xl">
          How the paper trader is learning from its own record. Every decision it
          makes — the trades it takes <span className="text-white">and</span> the
          setups it skips — is journaled, then graded against what the stock actually
          did. The real question isn&apos;t just P&amp;L: it&apos;s whether the{" "}
          <span className="text-white">signal</span> was right, whether we{" "}
          <span className="text-white">entered</span> on time, and whether we{" "}
          <span className="text-white">exited</span> on time — so a loss can be
          diagnosed, not just counted. Below: that signal-vs-execution split,
          whether it&apos;s improving week to week, a plain-English read of the tape,
          and which signals predict winners (with sample sizes and confidence
          intervals). The live positions and scorecard live on the{" "}
          <Link href="/paper" className="text-[var(--color-accent)] hover:underline">
            Paper
          </Link>{" "}
          tab.
        </p>
      </div>

      {hasAnyData ? (
        <>
          <ExecutionQuality report={execution} />
          <WeeklyProgress report={progress} />
          <Narrative report={narrative} />
          <Attribution report={attribution} />
        </>
      ) : (
        <EmptyState
          title="Nothing graded yet."
          hint="The journal is already recording every decision the paper trader makes — the setups it takes and the ones it skips. Weekly progress, the read of the tape, and signal attribution all appear here once trades close and their outcomes are labeled. Check the Paper tab for live positions in the meantime."
        />
      )}
    </div>
  );
}
