"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  api,
  AttributionResponse,
  NarrativeResponse,
  ProgressResponse,
} from "@/lib/api";
import { EmptyState, Spinner } from "@/components/ui";
import { WeeklyProgress } from "@/components/WeeklyProgress";
import { Narrative } from "@/components/Narrative";
import { Attribution } from "@/components/Attribution";

export default function LearningPage() {
  const [attribution, setAttribution] = useState<AttributionResponse | null>(null);
  const [narrative, setNarrative] = useState<NarrativeResponse | null>(null);
  const [progress, setProgress] = useState<ProgressResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    setLoading(true);
    // Each view loads independently; the page renders once all have settled so a
    // slow LLM narrative doesn't hold up the metrics.
    Promise.allSettled([
      api.paperProgress().then(setProgress),
      api.paperNarrative().then(setNarrative),
      api.paperAttribution().then(setAttribution),
    ]).then((results) => {
      if (results.every((r) => r.status === "rejected")) setError(true);
      setLoading(false);
    });
  }, []);

  if (loading) return <Spinner label="Loading learning…" />;
  if (error) return <EmptyState title="Couldn't load the learning data." />;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Learning</h1>
        <p className="text-[var(--color-muted)] mt-1 max-w-3xl">
          How the paper trader is learning from its own record. Every decision it
          makes — the trades it takes <span className="text-white">and</span> the
          setups it skips — is journaled, then graded against what the stock actually
          did. Below: whether it&apos;s getting better week to week, a plain-English
          read of the tape, and which signals actually predict winners (with sample
          sizes and confidence intervals, so small samples can&apos;t masquerade as
          edge). The live positions and scorecard live on the{" "}
          <Link href="/paper" className="text-[var(--color-accent)] hover:underline">
            Paper
          </Link>{" "}
          tab.
        </p>
      </div>

      <WeeklyProgress report={progress} />
      <Narrative report={narrative} />
      <Attribution report={attribution} />
    </div>
  );
}
