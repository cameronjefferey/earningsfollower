"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api, MorningBriefResponse, RankedSetup } from "@/lib/api";
import { PaywallBanner, PaywallFade } from "@/components/PaywallBanner";
import { RankedSetupCard } from "@/components/RankedSetupCard";
import { UpdatedAt } from "@/components/UpdatedAt";
import { BlurValue } from "@/components/BlurValue";
import { Card, EmptyState, Spinner, ThemePill } from "@/components/ui";
import { pct, signedPct, timingLabel } from "@/lib/format";
import { useAuthReady } from "@/lib/useAuthReady";

export default function BriefPage() {
  const { ready, accessToken } = useAuthReady();
  const { data: session } = useSession();
  const [data, setData] = useState<MorningBriefResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    setLoading(true);
    api
      .morningBrief(accessToken)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ready, accessToken]);

  const isPreview = Boolean(data?.preview);
  const bullets = data?.digest?.bullets ?? [];
  const focus: RankedSetup | null = data?.focus ?? data?.ranked?.[0] ?? null;
  const rest = (data?.ranked ?? []).filter((s) => s.id !== focus?.id);
  const today = data?.today_earnings ?? [];

  const pricingHref = `/pricing?next=${encodeURIComponent("/brief")}`;
  const ctaHref = session
    ? pricingHref
    : `/login?next=${encodeURIComponent(pricingHref)}`;

  return (
    <div>
      <div className="mb-8 max-w-2xl">
        <h1 className="text-3xl font-semibold tracking-tight">Morning brief</h1>
        <p className="text-base text-[var(--color-muted)] mt-3 leading-relaxed">
          The calendar shows who reports. The brief answers the only question that
          matters before the open:{" "}
          <span className="text-white">what should I actually lean on today?</span>
        </p>
        <UpdatedAt value={data?.updated_at || data?.generated_at} />
      </div>

      {isPreview ? (
        <div className="mb-8 space-y-4">
          <PaywallBanner
            title="See today's ranked lean — unlock the full brief"
            note="Pro gives you one focus setup each session with a clear action, what to watch, and when to drop it — plus the short board underneath. Calendar stays free."
            ctaLabel={session ? "Get Pro — $9.99/mo" : "Sign in to subscribe"}
          />
          <Card className="p-5 sm:p-6">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-accent)] mb-3">
              What you get every morning
            </div>
            <ol className="space-y-3 text-sm text-[var(--color-muted)]">
              <li className="flex gap-3">
                <span className="text-white font-semibold tabular shrink-0">1.</span>
                <span>
                  <span className="text-white font-medium">One focus setup</span> —
                  ticker, direction, and a plain-English action (not a 40-name board).
                </span>
              </li>
              <li className="flex gap-3">
                <span className="text-white font-semibold tabular shrink-0">2.</span>
                <span>
                  <span className="text-white font-medium">Watch / drop-if</span> —
                  what keeps the lean alive, and what kills it.
                </span>
              </li>
              <li className="flex gap-3">
                <span className="text-white font-semibold tabular shrink-0">3.</span>
                <span>
                  <span className="text-white font-medium">Honesty on the sample</span> —
                  n, win rate, and thin-history labels so you know when not to size up.
                </span>
              </li>
            </ol>
            <Link
              href={ctaHref}
              className="mt-5 inline-flex items-center justify-center rounded-lg bg-[var(--color-accent)] text-white text-sm font-medium px-4 py-2.5 hover:opacity-90"
            >
              {session ? "Unlock morning brief" : "Sign in to unlock"}
            </Link>
          </Card>
        </div>
      ) : null}

      {!ready || loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState title="Couldn't load brief." hint="Is the backend running?" />
      ) : (
        <div className="space-y-8">
          <section>
            <h2 className="text-sm font-semibold text-white mb-1">
              {isPreview ? "Today's focus (preview)" : "Today's focus"}
            </h2>
            <p className="text-sm text-[var(--color-muted)] mb-3 max-w-xl">
              {isPreview
                ? "A taste of the ranked lean. Subscribe to see the full action, watch, and drop-if notes."
                : "Start here. Everything else is secondary."}
            </p>
            {focus ? (
              isPreview ? (
                <PreviewFocusCard setup={focus} />
              ) : (
                <RankedSetupCard setup={focus} variant="hero" />
              )
            ) : (
              <EmptyState
                title="No focus setup yet."
                hint="Boards fill after the next data refresh."
              />
            )}
          </section>

          {rest.length && !isPreview ? (
            <section>
              <h2 className="text-sm font-semibold text-white mb-2">
                Also on the board
              </h2>
              <Card className="p-4">
                {rest.map((s) => (
                  <RankedSetupCard key={s.id} setup={s} variant="compact" />
                ))}
              </Card>
            </section>
          ) : null}

          {isPreview && rest.length ? (
            <section>
              <h2 className="text-sm font-semibold text-white mb-2">
                Also ranked today
              </h2>
              <Card className="p-4">
                <ul className="space-y-2">
                  {rest.map((s) => (
                    <li
                      key={s.id}
                      className="text-sm flex flex-wrap items-baseline gap-x-2 text-[var(--color-muted)]"
                    >
                      <span className="text-white font-medium">#{s.rank}</span>
                      <span className="text-white font-semibold">{s.ticker}</span>
                      <span>{s.headline}</span>
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-[var(--color-muted)] mt-3">
                  Full watch notes unlock with Pro.
                </p>
              </Card>
            </section>
          ) : null}

          <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              <h2 className="text-sm font-semibold text-white mb-2">What changed</h2>
              <Card className="p-4">
                {bullets.length ? (
                  <ul className="space-y-2">
                    {bullets.map((b, i) => (
                      <li key={i} className="text-sm flex gap-2">
                        <span className="text-[var(--color-accent)] shrink-0">•</span>
                        <span>{b.text}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-[var(--color-muted)]">
                    Quiet vs the last refresh.
                  </p>
                )}
              </Card>
            </div>

            <div>
              <h2 className="text-sm font-semibold text-white mb-2">Printing today</h2>
              <p className="text-xs text-[var(--color-muted)] mb-2">
                Free context from the calendar — who reports today.
              </p>
              {today.length ? (
                <Card className="p-4">
                  <ul className="divide-y divide-[var(--color-edge)]">
                    {today.map((c) => (
                      <li
                        key={c.ticker}
                        className="py-2 first:pt-0 last:pb-0 flex flex-wrap items-center gap-x-3 gap-y-1"
                      >
                        <Link
                          href={`/company/${c.ticker}`}
                          className="font-semibold hover:text-[var(--color-accent)]"
                        >
                          {c.ticker}
                        </Link>
                        <span className="text-xs text-[var(--color-muted)]">
                          {timingLabel(c.timing)}
                        </span>
                        {c.implied_move_pct != null ? (
                          <span className="text-xs text-[var(--color-muted)] tabular">
                            ~{pct(c.implied_move_pct, 0)} implied
                          </span>
                        ) : null}
                        <div className="flex flex-wrap gap-1 ml-auto">
                          {(c.themes ?? []).slice(0, 1).map((t) => (
                            <ThemePill key={t.key} theme={t} />
                          ))}
                        </div>
                      </li>
                    ))}
                  </ul>
                </Card>
              ) : (
                <p className="text-sm text-[var(--color-muted)]">
                  No names on today&apos;s calendar.
                </p>
              )}
            </div>
          </section>

          {isPreview ? (
            <PaywallFade label="Pro unlocks the full focus card — action, watch, and drop-if — every session." />
          ) : null}
        </div>
      )}
    </div>
  );
}

/** Readable teaser for unpaid users — sell the idea, lock the playbook. */
function PreviewFocusCard({ setup }: { setup: RankedSetup }) {
  const kindLabel = setup.kind === "wave" ? "Peer wave" : "Post-earnings drift";
  return (
    <Card className="p-5 sm:p-6 border-[var(--color-accent)]/35">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-accent)] mb-2">
        Example of today&apos;s focus · {kindLabel}
      </div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-2xl font-semibold tracking-tight">{setup.ticker}</div>
          {setup.name ? (
            <div className="text-sm text-[var(--color-muted)] mt-0.5">{setup.name}</div>
          ) : null}
          <p className="text-base mt-2">{setup.headline}</p>
        </div>
        {setup.edge_pct != null ? (
          <div className="text-right">
            <div className="text-xs text-[var(--color-muted)]">Hist. edge</div>
            <div className="text-xl font-semibold tabular">
              {signedPct(setup.edge_pct, 1)}
            </div>
          </div>
        ) : null}
      </div>
      <p className="text-sm text-[var(--color-muted)] mt-4 leading-relaxed">
        {setup.kind === "wave"
          ? "A peer already reported. Historically this name has drifted into its own print afterward — that's the lean we'd want you to evaluate."
          : "This name already printed. Historically similar prints kept drifting for a few sessions — that's the lean we'd want you to evaluate."}
      </p>
      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
        <div className="rounded-lg bg-[var(--color-panel-2)]/60 p-3">
          <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-1">
            Action (Pro)
          </div>
          <BlurValue active>
            <p>{setup.action || "Bias and timing for the session."}</p>
          </BlurValue>
        </div>
        <div className="rounded-lg bg-[var(--color-panel-2)]/60 p-3">
          <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-1">
            Drop if (Pro)
          </div>
          <BlurValue active>
            <p>{setup.invalidation}</p>
          </BlurValue>
        </div>
      </div>
    </Card>
  );
}
