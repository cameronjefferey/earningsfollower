"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Analyst,
  api,
  CompanyDetail,
  EarningsPlay,
  ImpliedMove,
  PlayLeg,
  ReactionSummary,
} from "@/lib/api";
import { BlurValue, BlurZone } from "@/components/BlurValue";
import { PaywallBanner, PaywallFade } from "@/components/PaywallBanner";
import { PeerWaveList } from "@/components/PeerWaveList";
import { PriceChart } from "@/components/PriceChart";
import { ReactionChart } from "@/components/ReactionChart";
import { Card, EmptyState, Spinner, Stat, ThemePill, VerdictPill } from "@/components/ui";
import { InfoTip } from "@/components/InfoTip";
import { glossary } from "@/lib/glossary";
import {
  fmtDate,
  marketCap,
  moveClass,
  pct,
  signedPct,
  timingLabel,
} from "@/lib/format";
import { useAuthReady } from "@/lib/useAuthReady";
import { FREE_COMPANY_LIMIT, recordCompanyView } from "@/lib/companyMeter";
import { reportFunnel } from "@/lib/ad-traffic";

/** Full-screen soft gate once a guest has spent their free company pages. */
function GuestGate({ ticker }: { ticker: string }) {
  const signupHref = `/login?mode=signup&next=${encodeURIComponent(`/company/${ticker}`)}`;
  const signinHref = `/login?next=${encodeURIComponent(`/company/${ticker}`)}`;
  return (
    <div className="max-w-md mx-auto mt-12">
      <Card className="p-6 space-y-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            That&apos;s your {FREE_COMPANY_LIMIT} free company pages
          </h1>
          <p className="text-sm text-[var(--color-muted)] mt-2 leading-relaxed">
            Create a free account for unlimited company pages - full reaction
            history, implied move context, and a live headline price. The
            calendar stays free either way.
          </p>
        </div>
        <Link
          href={signupHref}
          className="block w-full rounded-lg bg-[var(--color-accent)] text-white text-center font-medium py-2.5 hover:opacity-90"
        >
          Create free account
        </Link>
        <p className="text-xs text-[var(--color-muted)] text-center">
          Already have one?{" "}
          <Link href={signinHref} className="text-[var(--color-accent)] hover:underline">
            Sign in
          </Link>
          {" · "}
          <Link href="/calendar" className="text-[var(--color-accent)] hover:underline">
            Back to the calendar
          </Link>
        </p>
      </Card>
    </div>
  );
}

export default function CompanyPage() {
  const { ready, accessToken, session, status } = useAuthReady();
  const isAdmin = Boolean(session?.isAdmin);
  const params = useParams<{ ticker: string }>();
  const ticker = (params.ticker ?? "").toUpperCase();
  const [data, setData] = useState<CompanyDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [gated, setGated] = useState(false);
  const [freeViewsLeft, setFreeViewsLeft] = useState<number | null>(null);

  const isGuest = ready && status === "unauthenticated";

  useEffect(() => {
    if (!ticker || !ready) return;

    if (isGuest) {
      const meter = recordCompanyView(ticker);
      if (!meter.allowed) {
        reportFunnel("guest_gate", {
          path: `/company/${ticker}`,
          target: ticker,
          once: "gate",
        });
        setGated(true);
        setLoading(false);
        return;
      }
      reportFunnel("company_view", {
        path: `/company/${ticker}`,
        target: ticker,
        once: `co_${ticker}`,
      });
      setFreeViewsLeft(meter.remaining);
    }
    setGated(false);

    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .company(ticker, accessToken)
      .then((detail) => {
        if (cancelled) return;
        setData(detail);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
        setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker, ready, accessToken, isGuest]);

  if (gated) return <GuestGate ticker={ticker} />;
  if (!ready || loading) return <Spinner label={`Loading ${ticker}…`} />;
  if (error || !data)
    return (
      <EmptyState
        title={`No data for ${ticker}.`}
        hint="It may not be in the tracked universe yet. Add it to universe.yaml and refresh."
      />
    );

  const s = data.reactions.summary;
  const im = data.implied_move;

  const prices = data.price_history ?? [];
  const lastClose = prices.length ? prices[prices.length - 1].close : null;
  const displayPrice = data.last_price ?? lastClose;
  const dayChange = data.day_change_pct ?? null;
  const windowChange =
    prices.length > 1 && prices[0].close
      ? prices[prices.length - 1].close / prices[0].close - 1
      : null;
  const priceChange = dayChange ?? windowChange;
  const priceChangeLabel = dayChange !== null ? "today" : `${prices.length}d`;
  const earningsDates = data.reactions.events
    .map((e) => e.date)
    .filter((d): d is string => Boolean(d));

  const isPreview = Boolean(data.preview);
  const nextWhen = timingLabel(data.next_earnings_timing);

  return (
    <div>
      <Link
        href="/calendar"
        className="text-sm text-[var(--color-muted)] hover:text-white inline-flex items-center gap-1 mb-4"
      >
        ← Calendar
      </Link>

      {isPreview ? (
        <PaywallBanner
          title={`${data.ticker} - sample company brief`}
          badge="Sample"
          note={
            data.preview_note ||
            "Sample data for layout - key stats and charts are not the live brief. Pro unlocks the real numbers."
          }
        />
      ) : null}

      {isGuest && freeViewsLeft !== null ? (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-lg border border-[var(--color-edge)]/60 bg-[var(--color-panel)]/40 px-3 py-2 text-sm">
          <p className="min-w-0 text-[var(--color-muted)]">
            {freeViewsLeft > 0 ? (
              <>
                Guest view - {freeViewsLeft} of {FREE_COMPANY_LIMIT} free company{" "}
                {freeViewsLeft === 1 ? "page" : "pages"} left.
              </>
            ) : (
              <>Guest view - this is your last free company page.</>
            )}
          </p>
          <Link
            href={`/login?mode=signup&next=${encodeURIComponent(`/company/${ticker}`)}`}
            className="shrink-0 text-[var(--color-accent)] hover:underline"
          >
            Free account = unlimited
          </Link>
        </div>
      ) : null}

      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{data.ticker}</h1>
          <div className="text-[var(--color-muted)] mt-1">
            {data.name ?? "-"} {data.sector ? `· ${data.sector}` : ""}
          </div>
          <div className="flex flex-wrap gap-1.5 mt-3">
            {data.themes.map((t) => (
              <ThemePill key={t.key} theme={t} />
            ))}
          </div>
        </div>
        <Card className="px-4 py-3 text-right">
          <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
            Next earnings
          </div>
          <div className="text-lg font-semibold">
            {fmtDate(data.next_earnings_date)}
          </div>
          {!data.next_earnings_date ? (
            <div className="text-xs text-[var(--color-muted)]">Not scheduled</div>
          ) : nextWhen ? (
            <div className="text-xs text-[var(--color-muted)]">{nextWhen}</div>
          ) : null}
        </Card>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Stat
          label="Implied move"
          info={glossary.implied_move}
          value={im ? pct(im.expected_move_pct) : "-"}
          sub={
            im?.verdict ? <VerdictPill verdict={im.verdict} /> : im?.expiry ?? undefined
          }
          blur={isPreview}
        />
        <Stat
          label="Avg historical move"
          info={glossary.avg_move}
          value={pct(s.avg_abs_move_pct)}
          sub={`median ${pct(s.median_abs_move_pct)} · n=${s.sample_size}`}
          blur={isPreview}
        />
        <Stat
          label="Up rate"
          info={glossary.up_rate}
          value={pct(s.up_rate, 0)}
          sub={`avg ${signedPct(s.avg_move_pct)} drift ${signedPct(s.avg_drift_pct)}`}
          blur={isPreview}
        />
        <Stat
          label="Beat streak"
          info={glossary.beat_streak}
          value={s.beat_streak > 0 ? `${s.beat_streak}Q` : "-"}
          sub={s.beat_rate !== null ? `${pct(s.beat_rate, 0)} beat rate` : undefined}
          blur={isPreview}
        />
      </div>

      {prices.length > 1 ? (
        <Card className="p-4 mb-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
            <div className="flex items-baseline gap-3">
              <h2 className="font-semibold">Price</h2>
              {displayPrice !== null ? (
                <span className="text-2xl font-bold">
                  <BlurValue active={isPreview}>
                    ${Number(displayPrice).toFixed(2)}
                  </BlurValue>
                </span>
              ) : null}
              {priceChange !== null ? (
                <span className={`text-sm font-semibold ${moveClass(priceChange)}`}>
                  <BlurValue active={isPreview}>
                    {signedPct(priceChange)}{" "}
                    <span className="text-[var(--color-muted)] font-normal">
                      · {priceChangeLabel}
                    </span>
                  </BlurValue>
                </span>
              ) : null}
            </div>
            <span className="text-xs text-[var(--color-muted)] inline-flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full bg-[#f0a85b]" />
              earnings print
            </span>
          </div>
          <BlurZone active={isPreview} label="Sample chart">
            <PriceChart prices={prices} earningsDates={earningsDates} />
          </BlurZone>
        </Card>
      ) : null}

      {im ? (
        <Card className="p-4 mb-6">
          <div className="text-sm text-[var(--color-muted)]">
            Options market is pricing a{" "}
            <BlurValue active={isPreview}>
              <span className="text-white font-semibold">
                {pct(im.expected_move_pct)}
              </span>{" "}
              move by {im.expiry ?? "expiry"}
              {im.historical_avg_abs_move_pct
                ? `, vs a ${pct(im.historical_avg_abs_move_pct)} historical average`
                : ""}
              {im.richness ? ` (${im.richness.toFixed(2)}x).` : "."}{" "}
              {im.underlying_price ? `Spot ~$${im.underlying_price.toFixed(2)}.` : ""}
            </BlurValue>
          </div>
        </Card>
      ) : null}

      {isAdmin && data.playbook ? (
        <PlaybookCard play={data.playbook} ticker={data.ticker} />
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <VolEdgePanel im={im} blur={isPreview} />
        <PeadPanel s={s} blur={isPreview} />
        <AnalystPanel analyst={data.analyst} blur={isPreview} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="p-4 lg:col-span-2">
          <h2 className="font-semibold mb-3">Earnings reactions (close-to-close)</h2>
          <BlurZone active={isPreview} label="Sample reactions">
            <ReactionChart events={data.reactions.events} />
          </BlurZone>
        </Card>

        <Card className="p-4">
          <h2 className="font-semibold mb-1">Peer waves into {data.ticker}</h2>
          <p className="text-xs text-[var(--color-muted)] mb-3">
            How {data.ticker} has historically drifted after each peer reports, up to its
            own print.
          </p>
          <PeerWaveList peers={data.peers} blur={isPreview} />
        </Card>
      </div>

      <Card className="p-4 mt-6">
        <h2 className="font-semibold mb-3">Earnings history</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[var(--color-muted)] text-xs uppercase tracking-wide">
                <th className="py-2 pr-4">Date</th>
                <th className="py-2 pr-4">Timing</th>
                <th className="py-2 pr-4">EPS est / act</th>
                <th className="py-2 pr-4 cursor-help" title={glossary.surprise}>
                  Surprise
                </th>
                <th className="py-2 pr-4 cursor-help" title={glossary.move}>
                  Move
                </th>
                <th className="py-2 pr-4 cursor-help" title={glossary.gap}>
                  Gap
                </th>
                <th className="py-2 pr-4 cursor-help" title={glossary.drift}>
                  5d drift
                </th>
              </tr>
            </thead>
            <tbody>
              {[...data.reactions.events].reverse().map((e) => (
                <tr key={e.date} className="border-t border-[var(--color-edge)]">
                  <td className="py-2 pr-4">{fmtDate(e.date)}</td>
                  <td className="py-2 pr-4 text-[var(--color-muted)]">
                    {timingLabel(e.timing) ?? "-"}
                  </td>
                  <td className="py-2 pr-4">
                    <BlurValue active={isPreview}>
                      {e.eps_estimate ?? "-"} / {e.eps_actual ?? "-"}
                    </BlurValue>
                  </td>
                  <td className="py-2 pr-4">
                    <BlurValue active={isPreview}>{signedPct(e.surprise_pct)}</BlurValue>
                  </td>
                  <td className={`py-2 pr-4 font-medium ${moveClass(e.move_pct)}`}>
                    <BlurValue active={isPreview}>{signedPct(e.move_pct)}</BlurValue>
                  </td>
                  <td className={`py-2 pr-4 ${moveClass(e.gap_pct)}`}>
                    <BlurValue active={isPreview}>{signedPct(e.gap_pct)}</BlurValue>
                  </td>
                  <td className={`py-2 pr-4 ${moveClass(e.drift_pct)}`}>
                    <BlurValue active={isPreview}>{signedPct(e.drift_pct)}</BlurValue>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="text-xs text-[var(--color-muted)] mt-3">
          Market cap {marketCap(data.market_cap)}
          {data.exchange ? ` · ${data.exchange}` : ""}
          {isPreview ? " · demo numbers - subscribe for live history" : ""}
        </div>
      </Card>

      {isPreview ? (
        <PaywallFade label="Unlock the live company brief with Pro" />
      ) : null}
    </div>
  );
}

const DIR_COLOR: Record<string, string> = {
  bearish: "#f0556d",
  bullish: "#28c08a",
  neutral: "#8a97b1",
};

const VOL_LABEL: Record<string, { text: string; color: string }> = {
  sell: { text: "Sell premium", color: "#f0a85b" },
  buy: { text: "Buy premium", color: "#28c08a" },
  neutral: { text: "Vol fairly priced", color: "#8a97b1" },
};

const CONVICTION_COLOR: Record<string, string> = {
  high: "#28c08a",
  medium: "#f0a85b",
  low: "#8a97b1",
};

function Pill({ text, color }: { text: string; color: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border whitespace-nowrap"
      style={{ color, borderColor: `${color}55`, backgroundColor: `${color}1a` }}
    >
      {text}
    </span>
  );
}

function RangeBar({ play }: { play: EarningsPlay }) {
  const { expected_range_low: lo, expected_range_high: hi, spot } = play;
  if (lo === null || hi === null || spot === null || hi <= lo) return null;
  const pos = Math.min(100, Math.max(0, ((spot - lo) / (hi - lo)) * 100));
  return (
    <div className="mt-1">
      <div className="relative h-2 w-full rounded-full bg-[var(--color-panel-2)]">
        <div
          className="absolute -top-1 h-4 w-0.5 bg-white"
          style={{ left: `${pos}%` }}
        />
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-[var(--color-muted)]">
        <span>${lo.toFixed(0)}</span>
        <span className="text-white">spot ${spot.toFixed(0)}</span>
        <span>${hi.toFixed(0)}</span>
      </div>
    </div>
  );
}

function LegsTable({ legs }: { legs: PlayLeg[] }) {
  if (!legs.length) return null;
  return (
    <div className="rounded-lg border border-[var(--color-edge)] overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[var(--color-muted)] text-[11px] uppercase tracking-wide bg-[var(--color-panel-2)]">
            <th className="py-1.5 px-3">Leg</th>
            <th className="py-1.5 px-3">Strike</th>
            <th className="py-1.5 px-3">Why</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((leg, i) => {
            const buy = leg.action === "Buy";
            return (
              <tr key={i} className="border-t border-[var(--color-edge)]">
                <td className="py-1.5 px-3 whitespace-nowrap">
                  <span
                    className="font-semibold"
                    style={{ color: buy ? "#28c08a" : "#f0a85b" }}
                  >
                    {leg.action}
                  </span>{" "}
                  <span className="text-[var(--color-muted)]">{leg.option}</span>
                </td>
                <td className="py-1.5 px-3 font-semibold">
                  {leg.strike !== null ? `≈$${leg.strike}` : "-"}
                </td>
                <td className="py-1.5 px-3 text-[var(--color-muted)] text-xs">
                  {leg.note}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PlaybookCard({ play, ticker }: { play: EarningsPlay; ticker: string }) {
  const dirColor = DIR_COLOR[play.direction] ?? "#8a97b1";
  const vol = VOL_LABEL[play.vol_stance] ?? VOL_LABEL.neutral;
  const convColor = CONVICTION_COLOR[play.conviction] ?? "#8a97b1";

  return (
    <Card className="p-0 mb-6 overflow-hidden">
      <div
        className="px-4 py-3 border-b border-[var(--color-edge)]"
        style={{ background: `${dirColor}12` }}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold flex items-center">
            Earnings playbook
            <InfoTip text={glossary.playbook} />
          </h2>
          <div className="flex flex-wrap items-center gap-1.5">
            <Pill text={play.direction} color={dirColor} />
            <Pill text={vol.text} color={vol.color} />
            <Pill text={`${play.conviction} conviction`} color={convColor} />
          </div>
        </div>
        <div className="mt-1.5 text-lg font-bold" style={{ color: dirColor }}>
          {play.headline}
        </div>
        {play.conviction_basis?.tier_reason ? (
          <div className="mt-1 text-xs text-[var(--color-muted)]">
            Conviction basis: {play.conviction_basis.tier_reason}
          </div>
        ) : null}
      </div>

      <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
            The trade
          </div>
          <div className="font-semibold mt-0.5">{play.structure}</div>
          <p className="text-sm text-[var(--color-muted)] mt-1">
            {play.structure_detail}
          </p>

          <div className="mt-3">
            <LegsTable legs={play.legs} />
          </div>

          {play.expected_range_low !== null ? (
            <div className="mt-4">
              <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-1">
                Expected move range (options-implied)
              </div>
              <RangeBar play={play} />
            </div>
          ) : null}
        </div>

        <div className="space-y-4">
          <div>
            <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-1">
              When to put it on
            </div>
            <p className="text-sm">{play.timing}</p>
          </div>

          <div>
            <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-1">
              What invalidates it
            </div>
            <p className="text-sm">{play.invalidation}</p>
          </div>

          {play.bias_reasons.length ? (
            <div>
              <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-1">
                Why {play.direction}
              </div>
              <ul className="space-y-1">
                {play.bias_reasons.map((r, i) => (
                  <li key={i} className="text-sm flex gap-2">
                    <span style={{ color: dirColor }}>•</span>
                    <span className="text-[var(--color-muted)]">{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {play.vol_reasons.length ? (
            <div>
              <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)] mb-1">
                Why {vol.text.toLowerCase()}
              </div>
              <ul className="space-y-1">
                {play.vol_reasons.map((r, i) => (
                  <li key={i} className="text-sm flex gap-2">
                    <span style={{ color: vol.color }}>•</span>
                    <span className="text-[var(--color-muted)]">{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>

      {play.caveats.length ? (
        <div className="px-4 py-2.5 border-t border-[var(--color-edge)] bg-[var(--color-panel-2)]">
          {play.caveats.map((c, i) => (
            <div key={i} className="text-[11px] text-[var(--color-muted)] leading-relaxed">
              {c}
            </div>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

const EDGE_MAP: Record<string, { label: string; color: string; note: string }> = {
  seller_edge: {
    label: "Options look rich",
    color: "#f0a85b",
    note: "Realized moves rarely reach the implied move - historically a premium-seller edge.",
  },
  buyer_edge: {
    label: "Options look cheap",
    color: "#28c08a",
    note: "Realized moves often exceed the implied move - historically a premium-buyer edge.",
  },
  balanced: {
    label: "Fairly priced",
    color: "#8a97b1",
    note: "Realized moves land near the implied move about as often as not.",
  },
};

function VolEdgePanel({ im, blur = false }: { im: ImpliedMove | null; blur?: boolean }) {
  const edge = im?.edge_verdict ? EDGE_MAP[im.edge_verdict] : null;
  return (
    <Card className="p-4">
      <h2 className="font-semibold flex items-center">
        Vol edge
        <InfoTip text={glossary.vol_edge} />
      </h2>
      {im && im.exceed_rate != null && edge ? (
        <>
          <BlurValue active={blur}>
            <div
              className="mt-2 inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border"
              style={{ color: edge.color, borderColor: `${edge.color}55`, backgroundColor: `${edge.color}1a` }}
            >
              {edge.label}
            </div>
          </BlurValue>
          <div className="mt-3 text-sm">
            Realized move reached the{" "}
            <BlurValue active={blur}>
              <span className="font-semibold">{pct(im.expected_move_pct)}</span> implied
              move{" "}
              <span className="font-semibold">{pct(im.exceed_rate, 0)}</span> of the time.
            </BlurValue>
          </div>
          <div className="text-xs text-[var(--color-muted)] mt-2">
            <BlurValue active={blur}>
              {edge.note} (n={im.edge_sample})
            </BlurValue>
          </div>
        </>
      ) : (
        <div className="text-sm text-[var(--color-muted)] mt-3">
          {blur
            ? "Vol-edge stats unlock with Pro."
            : "Need a live implied move and a few past prints to gauge the edge."}
        </div>
      )}
    </Card>
  );
}

function PeadPanel({ s, blur = false }: { s: ReactionSummary; blur?: boolean }) {
  const rows = [
    { label: "After a beat", value: s.avg_drift_after_beat_pct },
    { label: "After a miss", value: s.avg_drift_after_miss_pct },
  ];
  return (
    <Card className="p-4">
      <h2 className="font-semibold flex items-center">
        Post-earnings drift
        <InfoTip text={glossary.pead} />
      </h2>
      <div className="text-xs text-[var(--color-muted)] mb-2">5 trading days after the report</div>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between text-sm">
            <span className="text-[var(--color-muted)]">{r.label}</span>
            <span className={`font-semibold ${moveClass(r.value)}`}>
              <BlurValue active={blur}>{signedPct(r.value)}</BlurValue>
            </span>
          </div>
        ))}
        <div className="flex items-center justify-between text-sm pt-1.5 border-t border-[var(--color-edge)]">
          <span className="text-[var(--color-muted)]">Continuation rate</span>
          <span className="font-semibold">
            <BlurValue active={blur}>{pct(s.continuation_rate, 0)}</BlurValue>
          </span>
        </div>
      </div>
    </Card>
  );
}

function AnalystPanel({
  analyst,
  blur = false,
}: {
  analyst: Analyst | null;
  blur?: boolean;
}) {
  if (!analyst) {
    return (
      <Card className="p-4">
        <h2 className="font-semibold flex items-center">
          Analyst ratings
          <InfoTip text={glossary.analyst_ratings} />
        </h2>
        <div className="text-sm text-[var(--color-muted)] mt-3">
          No analyst data for this ticker. On Financial Modeling Prep&apos;s free tier,
          price targets and ratings are only available for a handful of large caps
          (e.g. AAPL, AMD, AMZN, GOOGL, INTC). Upgrade your FMP plan to unlock the rest.
        </div>
      </Card>
    );
  }

  const r = analyst.ratings;
  const total = analyst.ratings_total || 1;
  const bullish = r.strong_buy + r.buy;
  const neutral = r.hold;
  const bearish = r.sell + r.strong_sell;
  const trendColor =
    analyst.trend === "improving"
      ? "#28c08a"
      : analyst.trend === "deteriorating"
      ? "#f0556d"
      : "#8a97b1";

  return (
    <Card className="p-4">
      <h2 className="font-semibold flex items-center">
        Analyst ratings
        <InfoTip text={glossary.analyst_ratings} />
      </h2>

      {analyst.price_target ? (
        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-2xl font-bold">
            <BlurValue active={blur}>${analyst.price_target.toFixed(0)}</BlurValue>
          </span>
          {analyst.upside_pct !== null ? (
            <span className={`text-sm font-semibold ${moveClass(analyst.upside_pct)}`}>
              <BlurValue active={blur}>{signedPct(analyst.upside_pct)} vs spot</BlurValue>
            </span>
          ) : null}
        </div>
      ) : null}

      {analyst.ratings_total > 0 ? (
        <>
          <BlurZone active={blur} label="Sample">
            <div className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-[var(--color-panel-2)]">
              <div style={{ width: `${(bullish / total) * 100}%`, background: "#28c08a" }} />
              <div style={{ width: `${(neutral / total) * 100}%`, background: "#8a97b1" }} />
              <div style={{ width: `${(bearish / total) * 100}%`, background: "#f0556d" }} />
            </div>
          </BlurZone>
          <div className="mt-2 flex items-center justify-between text-xs text-[var(--color-muted)]">
            <BlurValue active={blur}>
              <span>
                {bullish} buy · {neutral} hold · {bearish} sell
              </span>
            </BlurValue>
            {analyst.trend ? (
              <BlurValue active={blur}>
                <span style={{ color: trendColor }} className="font-medium">
                  {analyst.trend}
                </span>
              </BlurValue>
            ) : null}
          </div>
        </>
      ) : null}
    </Card>
  );
}
