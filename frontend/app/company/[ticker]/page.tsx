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

export default function CompanyPage() {
  const params = useParams<{ ticker: string }>();
  const ticker = (params.ticker ?? "").toUpperCase();
  const [data, setData] = useState<CompanyDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    api
      .company(ticker)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [ticker]);

  if (loading) return <Spinner label={`Loading ${ticker}…`} />;
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
  const priceChange =
    prices.length > 1 && prices[0].close
      ? prices[prices.length - 1].close / prices[0].close - 1
      : null;
  const earningsDates = data.reactions.events
    .map((e) => e.date)
    .filter((d): d is string => Boolean(d));

  return (
    <div>
      <Link
        href="/"
        className="text-sm text-[var(--color-muted)] hover:text-white inline-flex items-center gap-1 mb-4"
      >
        ← Calendar
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{data.ticker}</h1>
          <div className="text-[var(--color-muted)] mt-1">
            {data.name ?? "—"} {data.sector ? `· ${data.sector}` : ""}
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
          <div className="text-xs text-[var(--color-muted)]">
            {data.next_earnings_date
              ? timingLabel(data.next_earnings_timing)
              : "Not scheduled"}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Stat
          label="Implied move"
          info={glossary.implied_move}
          value={im ? pct(im.expected_move_pct) : "—"}
          sub={
            im?.verdict ? <VerdictPill verdict={im.verdict} /> : im?.expiry ?? undefined
          }
        />
        <Stat
          label="Avg historical move"
          info={glossary.avg_move}
          value={pct(s.avg_abs_move_pct)}
          sub={`median ${pct(s.median_abs_move_pct)} · n=${s.sample_size}`}
        />
        <Stat
          label="Up rate"
          info={glossary.up_rate}
          value={pct(s.up_rate, 0)}
          sub={`avg ${signedPct(s.avg_move_pct)} drift ${signedPct(s.avg_drift_pct)}`}
        />
        <Stat
          label="Beat streak"
          info={glossary.beat_streak}
          value={s.beat_streak > 0 ? `${s.beat_streak}Q` : "—"}
          sub={s.beat_rate !== null ? `${pct(s.beat_rate, 0)} beat rate` : undefined}
        />
      </div>

      {prices.length > 1 ? (
        <Card className="p-4 mb-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
            <div className="flex items-baseline gap-3">
              <h2 className="font-semibold">Price</h2>
              {lastClose !== null ? (
                <span className="text-2xl font-bold">${lastClose.toFixed(2)}</span>
              ) : null}
              {priceChange !== null ? (
                <span className={`text-sm font-semibold ${moveClass(priceChange)}`}>
                  {signedPct(priceChange)}{" "}
                  <span className="text-[var(--color-muted)] font-normal">
                    · {prices.length}d
                  </span>
                </span>
              ) : null}
            </div>
            <span className="text-xs text-[var(--color-muted)] inline-flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full bg-[#f0a85b]" />
              earnings print
            </span>
          </div>
          <PriceChart prices={prices} earningsDates={earningsDates} />
        </Card>
      ) : null}

      {im ? (
        <Card className="p-4 mb-6">
          <div className="text-sm text-[var(--color-muted)]">
            Options market is pricing a{" "}
            <span className="text-white font-semibold">
              {pct(im.expected_move_pct)}
            </span>{" "}
            move by {im.expiry ?? "expiry"}
            {im.historical_avg_abs_move_pct
              ? `, vs a ${pct(im.historical_avg_abs_move_pct)} historical average`
              : ""}
            {im.richness ? ` (${im.richness.toFixed(2)}x).` : "."}{" "}
            {im.underlying_price ? `Spot ~$${im.underlying_price.toFixed(2)}.` : ""}
          </div>
        </Card>
      ) : null}

      {data.playbook ? <PlaybookCard play={data.playbook} ticker={data.ticker} /> : null}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <VolEdgePanel im={im} />
        <PeadPanel s={s} />
        <AnalystPanel analyst={data.analyst} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="p-4 lg:col-span-2">
          <h2 className="font-semibold mb-3">Earnings reactions (close-to-close)</h2>
          <ReactionChart events={data.reactions.events} />
        </Card>

        <Card className="p-4">
          <h2 className="font-semibold mb-1">Peer waves into {data.ticker}</h2>
          <p className="text-xs text-[var(--color-muted)] mb-3">
            How {data.ticker} has historically drifted after each peer reports, up to its
            own print.
          </p>
          <PeerWaveList peers={data.peers} />
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
                    {timingLabel(e.timing)}
                  </td>
                  <td className="py-2 pr-4">
                    {e.eps_estimate ?? "—"} / {e.eps_actual ?? "—"}
                  </td>
                  <td className="py-2 pr-4">{signedPct(e.surprise_pct)}</td>
                  <td className={`py-2 pr-4 font-medium ${moveClass(e.move_pct)}`}>
                    {signedPct(e.move_pct)}
                  </td>
                  <td className={`py-2 pr-4 ${moveClass(e.gap_pct)}`}>
                    {signedPct(e.gap_pct)}
                  </td>
                  <td className={`py-2 pr-4 ${moveClass(e.drift_pct)}`}>
                    {signedPct(e.drift_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="text-xs text-[var(--color-muted)] mt-3">
          Market cap {marketCap(data.market_cap)}
          {data.exchange ? ` · ${data.exchange}` : ""}
        </div>
      </Card>
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
    <div className="rounded-lg border border-[var(--color-edge)] overflow-hidden">
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
                  {leg.strike !== null ? `≈$${leg.strike}` : "—"}
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
    note: "Realized moves rarely reach the implied move — historically a premium-seller edge.",
  },
  buyer_edge: {
    label: "Options look cheap",
    color: "#28c08a",
    note: "Realized moves often exceed the implied move — historically a premium-buyer edge.",
  },
  balanced: {
    label: "Fairly priced",
    color: "#8a97b1",
    note: "Realized moves land near the implied move about as often as not.",
  },
};

function VolEdgePanel({ im }: { im: ImpliedMove | null }) {
  const edge = im?.edge_verdict ? EDGE_MAP[im.edge_verdict] : null;
  return (
    <Card className="p-4">
      <h2 className="font-semibold flex items-center">
        Vol edge
        <InfoTip text={glossary.vol_edge} />
      </h2>
      {im && im.exceed_rate !== null && edge ? (
        <>
          <div
            className="mt-2 inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border"
            style={{ color: edge.color, borderColor: `${edge.color}55`, backgroundColor: `${edge.color}1a` }}
          >
            {edge.label}
          </div>
          <div className="mt-3 text-sm">
            Realized move reached the{" "}
            <span className="font-semibold">{pct(im.expected_move_pct)}</span> implied
            move{" "}
            <span className="font-semibold">{pct(im.exceed_rate, 0)}</span> of the time.
          </div>
          <div className="text-xs text-[var(--color-muted)] mt-2">
            {edge.note} (n={im.edge_sample})
          </div>
        </>
      ) : (
        <div className="text-sm text-[var(--color-muted)] mt-3">
          Need a live implied move and a few past prints to gauge the edge.
        </div>
      )}
    </Card>
  );
}

function PeadPanel({ s }: { s: ReactionSummary }) {
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
              {signedPct(r.value)}
            </span>
          </div>
        ))}
        <div className="flex items-center justify-between text-sm pt-1.5 border-t border-[var(--color-edge)]">
          <span className="text-[var(--color-muted)]">Continuation rate</span>
          <span className="font-semibold">{pct(s.continuation_rate, 0)}</span>
        </div>
      </div>
    </Card>
  );
}

function AnalystPanel({ analyst }: { analyst: Analyst | null }) {
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
          <span className="text-2xl font-bold">${analyst.price_target.toFixed(0)}</span>
          {analyst.upside_pct !== null ? (
            <span className={`text-sm font-semibold ${moveClass(analyst.upside_pct)}`}>
              {signedPct(analyst.upside_pct)} vs spot
            </span>
          ) : null}
        </div>
      ) : null}

      {analyst.ratings_total > 0 ? (
        <>
          <div className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-[var(--color-panel-2)]">
            <div style={{ width: `${(bullish / total) * 100}%`, background: "#28c08a" }} />
            <div style={{ width: `${(neutral / total) * 100}%`, background: "#8a97b1" }} />
            <div style={{ width: `${(bearish / total) * 100}%`, background: "#f0556d" }} />
          </div>
          <div className="mt-2 flex items-center justify-between text-xs text-[var(--color-muted)]">
            <span>{bullish} buy · {neutral} hold · {bearish} sell</span>
            {analyst.trend ? (
              <span style={{ color: trendColor }} className="font-medium">
                {analyst.trend}
              </span>
            ) : null}
          </div>
        </>
      ) : null}
    </Card>
  );
}
