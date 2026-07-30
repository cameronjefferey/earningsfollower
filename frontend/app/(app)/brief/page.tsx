"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api, MorningBriefResponse, RankedSetup } from "@/lib/api";
import { BlurZone } from "@/components/BlurValue";
import { PaywallBanner } from "@/components/PaywallBanner";
import { RankedSetupCard } from "@/components/RankedSetupCard";
import { FocusHero, BoardQualityBar } from "@/components/brief/FocusHero";
import { UpdatedAt } from "@/components/UpdatedAt";
import { Card, EmptyState, Spinner, ThemePill } from "@/components/ui";
import { pct, timingLabel } from "@/lib/format";
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
  const quality = data?.board_quality;

  const pricingHref = `/pricing?next=${encodeURIComponent("/brief")}`;
  const ctaHref = session
    ? pricingHref
    : `/login?next=${encodeURIComponent(pricingHref)}`;

  return (
    <div>
      <div className="mb-8 max-w-2xl">
        <h1 className="text-3xl font-semibold tracking-tight">Morning brief</h1>
        <p className="text-base text-[var(--color-muted)] mt-3 leading-relaxed">
          One ranked lean for the session — the thesis, a plan with levels, and the
          honest read on how strong today&apos;s board actually is.
        </p>
        <UpdatedAt value={data?.updated_at || data?.generated_at} />
      </div>

      {isPreview ? (
        <div className="mb-8">
          <PaywallBanner
            title="See today's ranked lean — unlock the full brief"
            note="Pro gives you the focus setup with a conviction score, a plan (target, window, invalidation, sizing), and the rest of the wave. Calendar stays free."
            ctaLabel={session ? "Get Pro" : "Sign in to subscribe"}
          />
        </div>
      ) : null}

      {!ready || loading ? (
        <Spinner />
      ) : error ? (
        <EmptyState title="Couldn't load brief." hint="Is the backend running?" />
      ) : (
        <div className="space-y-8">
          <section>
            <div className="flex items-baseline justify-between gap-3 mb-3">
              <h2 className="text-sm font-semibold text-white">
                {isPreview ? "Today's focus (preview)" : "Today's focus"}
              </h2>
              <span className="text-xs text-[var(--color-muted)]">
                Start here. Everything else is secondary.
              </span>
            </div>
            {focus ? (
              <FocusHero setup={focus} preview={isPreview} />
            ) : (
              <EmptyState
                title="No focus setup yet."
                hint="Boards fill after the next data refresh."
              />
            )}
          </section>

          {!isPreview && quality ? (
            <section>
              <BoardQualityBar q={quality} />
            </section>
          ) : null}

          {rest.length ? (
            <section>
              <h2 className="text-sm font-semibold text-white mb-2">
                {isPreview ? "Also ranked today" : "Other independent drivers"}
              </h2>
              {isPreview ? (
                <Card className="p-4">
                  <BlurZone active label="Pro — full board">
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
                  </BlurZone>
                  <p className="text-xs text-[var(--color-muted)] mt-3">
                    Full board, plan, and levels unlock with Pro.
                  </p>
                </Card>
              ) : (
                <Card className="p-4">
                  {rest.map((s) => (
                    <RankedSetupCard key={s.id} setup={s} variant="compact" />
                  ))}
                </Card>
              )}
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
              <h2 className="text-sm font-semibold text-white mb-2">Reports today</h2>
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
            <Card className="p-5 sm:p-6 border-[var(--color-accent)]/30">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-accent)] mb-3">
                What Pro unlocks every morning
              </div>
              <ol className="space-y-3 text-sm text-[var(--color-muted)]">
                <li className="flex gap-3">
                  <span className="text-white font-semibold tabular shrink-0">1.</span>
                  <span>
                    <span className="text-white font-medium">A ranked focus</span> with a
                    conviction score — one lean, not a 40-name board.
                  </span>
                </li>
                <li className="flex gap-3">
                  <span className="text-white font-semibold tabular shrink-0">2.</span>
                  <span>
                    <span className="text-white font-medium">A plan</span> — target,
                    window, invalidation, and sizing, tied to the sample.
                  </span>
                </li>
                <li className="flex gap-3">
                  <span className="text-white font-semibold tabular shrink-0">3.</span>
                  <span>
                    <span className="text-white font-medium">An honest board read</span> —
                    breadth, sample strength, and when it&apos;s a narrow day.
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
          ) : null}
        </div>
      )}
    </div>
  );
}
