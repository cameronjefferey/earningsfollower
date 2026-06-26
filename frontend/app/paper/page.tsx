"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, PaperResponse, PaperTrade, PaperBucket } from "@/lib/api";
import { Card, EmptyState, Spinner, Stat } from "@/components/ui";
import { fmtDate, moveClass } from "@/lib/format";

const DIR_COLOR: Record<string, string> = {
  bearish: "#f0556d",
  bullish: "#28c08a",
  neutral: "#8a97b1",
};

const STATUS_COLOR: Record<string, string> = {
  pending: "#f0a85b",
  open: "#5b8cff",
  closing: "#b06bff",
  closed: "#8a97b1",
  canceled: "#5a6680",
};

function money(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

function signedMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return (v > 0 ? "+" : "") + money(v, 0);
}

const STRATEGY_META: Record<string, { label: string; color: string }> = {
  earnings: { label: "earnings", color: "#2dd4bf" },
  waves: { label: "wave", color: "#b06bff" },
  drift: { label: "drift", color: "#818cf8" },
};

function strategyMeta(strategy: string | undefined) {
  return STRATEGY_META[strategy ?? "earnings"] ?? STRATEGY_META.earnings;
}

function Pill({ text, color }: { text: string; color: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold border whitespace-nowrap"
      style={{ color, borderColor: `${color}55`, backgroundColor: `${color}1a` }}
    >
      {text}
    </span>
  );
}

function Legs({ trade }: { trade: PaperTrade }) {
  if (!trade.legs?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {trade.legs.map((l) => (
        <span
          key={l.symbol}
          className="text-[11px] rounded border border-[var(--color-edge)] px-1.5 py-0.5 font-mono"
          style={{ color: l.side === "sell" ? "#f0a85b" : "#28c08a" }}
        >
          {l.side === "sell" ? "S" : "B"} {l.strike}
          {l.type === "call" ? "C" : "P"}
        </span>
      ))}
    </div>
  );
}

const PROFIT = "#28c08a";
const LOSS = "#f0556d";

// Derive the payoff geometry of a credit spread / iron condor from its legs so
// we can show, in price terms, where the position makes or loses money.
function payoffGeometry(trade: PaperTrade) {
  const legs = trade.legs ?? [];
  const find = (type: "call" | "put", side: "buy" | "sell") =>
    legs.find((l) => l.type === type && l.side === side)?.strike ?? null;
  const sc = find("call", "sell"); // short call
  const lc = find("call", "buy"); // long call (cap)
  const sp = find("put", "sell"); // short put
  const lp = find("put", "buy"); // long put (cap)
  const credit = trade.entry_credit ?? 0;
  const contracts = trade.contracts ?? 1;
  if (credit <= 0 || (sc === null && sp === null)) return null;

  const maxProfit = credit * 100 * contracts;
  const maxLoss = trade.max_risk ?? null;
  const upperBE = sc !== null ? sc + credit : null;
  const lowerBE = sp !== null ? sp - credit : null;
  const entry = trade.spot_entry ?? null;
  const now = trade.spot_now ?? null;
  const spot = now ?? entry; // current price preferred for positioning

  const strikes = [sc, lc, sp, lp].filter((x): x is number => x !== null);
  const marks = [...strikes, entry, now].filter((x): x is number => x !== null);
  const loS = Math.min(...marks);
  const hiS = Math.max(...marks);
  const pad = Math.max((hiS - loS) * 0.12, 1);
  const domLo = loS - pad;
  const domHi = hiS + pad;

  const pnlPerShare = (S: number) => {
    let loss = 0;
    if (sc !== null && lc !== null) loss += Math.min(Math.max(S - sc, 0), lc - sc);
    if (sp !== null && lp !== null) loss += Math.min(Math.max(sp - S, 0), sp - lp);
    return credit - loss;
  };

  return {
    sc, lc, sp, lp, credit, contracts, maxProfit, maxLoss,
    upperBE, lowerBE, spot, entry, now, domLo, domHi, pnlPerShare,
  };
}

type Geometry = NonNullable<ReturnType<typeof payoffGeometry>>;

function PayoffBar({ g }: { g: Geometry }) {
  const N = 48;
  const span = g.domHi - g.domLo || 1;
  const pct = (x: number) => Math.max(0, Math.min(100, ((x - g.domLo) / span) * 100));
  const cells = Array.from({ length: N }, (_, i) => {
    const S = g.domLo + ((i + 0.5) / N) * span;
    const profit = g.pnlPerShare(S) > 0;
    const full = (g.sp === null || S >= g.sp) && (g.sc === null || S <= g.sc);
    return profit ? (full ? PROFIT : `${PROFIT}66`) : `${LOSS}3a`;
  });

  // Show the entry marker only when it's drifted a visible distance from now.
  const showEntry =
    g.entry != null && g.now != null && Math.abs(g.now - g.entry) / span > 0.02;
  const nowLabel = g.now != null;
  const moveFromEntry =
    g.now != null && g.entry ? (g.now / g.entry - 1) * 100 : null;

  return (
    <div className="mt-3">
      <div className="relative">
        {g.spot != null ? (
          <div
            className="absolute -top-4 -translate-x-1/2 whitespace-nowrap text-[10px] font-semibold text-white"
            style={{ left: `${pct(g.spot)}%` }}
          >
            {nowLabel ? "now " : "entry "}
            {money(g.spot)}
            {moveFromEntry != null ? (
              <span
                className="ml-1 font-normal"
                style={{ color: moveFromEntry >= 0 ? PROFIT : LOSS }}
              >
                ({moveFromEntry >= 0 ? "+" : ""}
                {moveFromEntry.toFixed(1)}%)
              </span>
            ) : null}
          </div>
        ) : null}
        <div className="flex h-7 w-full overflow-hidden rounded">
          {cells.map((c, i) => (
            <div key={i} style={{ width: `${100 / N}%`, backgroundColor: c }} />
          ))}
        </div>
        {showEntry && g.entry != null ? (
          <div
            className="absolute top-0 bottom-0 border-l border-dashed border-[#8a97b1]"
            style={{ left: `${pct(g.entry)}%` }}
          />
        ) : null}
        {g.spot != null ? (
          <div
            className="absolute top-0 bottom-0 w-px bg-white"
            style={{ left: `${pct(g.spot)}%` }}
          />
        ) : null}
      </div>
      <div className="relative mt-1 h-3 text-[10px] text-[var(--color-muted)]">
        {g.lowerBE != null ? (
          <span className="absolute -translate-x-1/2" style={{ left: `${pct(g.lowerBE)}%` }}>
            {money(g.lowerBE)}
          </span>
        ) : null}
        {showEntry && g.entry != null ? (
          <span
            className="absolute -translate-x-1/2 text-[#8a97b1]"
            style={{ left: `${pct(g.entry)}%` }}
          >
            entry
          </span>
        ) : null}
        {g.upperBE != null ? (
          <span className="absolute -translate-x-1/2" style={{ left: `${pct(g.upperBE)}%` }}>
            {money(g.upperBE)}
          </span>
        ) : null}
      </div>
      <div className="mt-1 flex items-center gap-3 text-[10px] text-[var(--color-muted)]">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: PROFIT }} />
          profit
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: `${LOSS}3a` }} />
          loss
        </span>
        <span className="ml-auto">break-even prices ↑</span>
      </div>
    </div>
  );
}

function PlainEnglish({ g, trade }: { g: Geometry; trade: PaperTrade }) {
  const exp = fmtDate(trade.expiration);
  const band =
    g.sp != null && g.sc != null
      ? `between ${money(g.sp)} and ${money(g.sc)}`
      : g.sc != null
      ? `below ${money(g.sc)}`
      : `above ${money(g.sp)}`;
  const movePct =
    trade.expected_move_pct != null
      ? `±${(trade.expected_move_pct * 100).toFixed(1)}%`
      : null;
  return (
    <p className="mt-2 text-xs leading-relaxed text-[var(--color-muted)]">
      Keep the full{" "}
      <span className="font-semibold" style={{ color: PROFIT }}>
        {money(g.maxProfit)}
      </span>{" "}
      if {trade.ticker} closes {band} by {exp}. Start losing past{" "}
      <span className="text-white">{money(g.lowerBE)}</span> /{" "}
      <span className="text-white">{money(g.upperBE)}</span>; full{" "}
      <span className="font-semibold" style={{ color: LOSS }}>
        {money(g.maxLoss)}
      </span>{" "}
      loss beyond {money(g.lp)} / {money(g.lc)}.
      {movePct ? (
        <>
          {" "}
          The options price a {movePct} move by then — this wins if the actual move
          comes in smaller.
        </>
      ) : null}
    </p>
  );
}

// Derive the payoff geometry of a directional debit spread (drift / PEAD) from
// its legs: a bull call (bullish) or bear put (bearish) spread. Unlike a credit
// spread it's one-sided — max loss is the debit, max profit is width minus debit.
function driftGeometry(trade: PaperTrade) {
  const legs = trade.legs ?? [];
  const long = trade.direction === "bullish"; // bull call vs bear put
  const otype: "call" | "put" = long ? "call" : "put";
  const longLeg = legs.find((l) => l.type === otype && l.side === "buy")?.strike ?? null;
  const shortLeg = legs.find((l) => l.type === otype && l.side === "sell")?.strike ?? null;
  const debit = trade.entry_credit ?? 0; // for debit trades, entry_credit holds the debit
  const contracts = trade.contracts ?? 1;
  if (debit <= 0 || longLeg === null || shortLeg === null) return null;

  const width = Math.abs(shortLeg - longLeg);
  const maxLoss = trade.max_risk ?? debit * 100 * contracts;
  const maxProfit = Math.max(0, (width - debit) * 100 * contracts);
  const breakeven = long ? longLeg + debit : longLeg - debit;

  const entry = trade.spot_entry ?? null;
  const now = trade.spot_now ?? null;
  const spot = now ?? entry;

  const marks = [longLeg, shortLeg, entry, now].filter((x): x is number => x !== null);
  const loS = Math.min(...marks);
  const hiS = Math.max(...marks);
  const pad = Math.max((hiS - loS) * 0.12, 1);
  const domLo = loS - pad;
  const domHi = hiS + pad;

  const pnlPerShare = (S: number) => {
    const intrinsic = long
      ? Math.min(Math.max(S - longLeg, 0), width)
      : Math.min(Math.max(longLeg - S, 0), width);
    return intrinsic - debit;
  };

  return {
    long, longLeg, shortLeg, debit, contracts, width, maxLoss, maxProfit,
    breakeven, entry, now, spot, domLo, domHi, pnlPerShare,
  };
}

type DriftGeo = NonNullable<ReturnType<typeof driftGeometry>>;

function RiskBoxes({ maxProfit, maxLoss }: { maxProfit: number; maxLoss: number | null }) {
  return (
    <div className="mt-3 grid grid-cols-2 gap-2">
      <div
        className="rounded-lg border px-3 py-2"
        style={{ borderColor: `${PROFIT}40`, background: `${PROFIT}12` }}
      >
        <div className="text-[10px] uppercase text-[var(--color-muted)]">Max profit</div>
        <div className="font-bold" style={{ color: PROFIT }}>{money(maxProfit)}</div>
      </div>
      <div
        className="rounded-lg border px-3 py-2"
        style={{ borderColor: `${LOSS}40`, background: `${LOSS}12` }}
      >
        <div className="text-[10px] uppercase text-[var(--color-muted)]">Max loss</div>
        <div className="font-bold" style={{ color: LOSS }}>{money(maxLoss)}</div>
      </div>
    </div>
  );
}

function DriftPayoffBar({ g }: { g: DriftGeo }) {
  const N = 48;
  const span = g.domHi - g.domLo || 1;
  const pct = (x: number) => Math.max(0, Math.min(100, ((x - g.domLo) / span) * 100));
  const cells = Array.from({ length: N }, (_, i) => {
    const S = g.domLo + ((i + 0.5) / N) * span;
    if (g.pnlPerShare(S) <= 0) return `${LOSS}3a`;
    const full = g.long ? S >= g.shortLeg : S <= g.shortLeg;
    return full ? PROFIT : `${PROFIT}66`;
  });

  const showEntry =
    g.entry != null && g.now != null && Math.abs(g.now - g.entry) / span > 0.02;
  const nowLabel = g.now != null;
  const moveFromEntry = g.now != null && g.entry ? (g.now / g.entry - 1) * 100 : null;

  return (
    <div className="mt-3">
      <div className="relative">
        {g.spot != null ? (
          <div
            className="absolute -top-4 -translate-x-1/2 whitespace-nowrap text-[10px] font-semibold text-white"
            style={{ left: `${pct(g.spot)}%` }}
          >
            {nowLabel ? "now " : "entry "}
            {money(g.spot)}
            {moveFromEntry != null ? (
              <span
                className="ml-1 font-normal"
                style={{ color: moveFromEntry >= 0 ? PROFIT : LOSS }}
              >
                ({moveFromEntry >= 0 ? "+" : ""}
                {moveFromEntry.toFixed(1)}%)
              </span>
            ) : null}
          </div>
        ) : null}
        <div className="flex h-7 w-full overflow-hidden rounded">
          {cells.map((c, i) => (
            <div key={i} style={{ width: `${100 / N}%`, backgroundColor: c }} />
          ))}
        </div>
        {showEntry && g.entry != null ? (
          <div
            className="absolute top-0 bottom-0 border-l border-dashed border-[#8a97b1]"
            style={{ left: `${pct(g.entry)}%` }}
          />
        ) : null}
        {g.spot != null ? (
          <div
            className="absolute top-0 bottom-0 w-px bg-white"
            style={{ left: `${pct(g.spot)}%` }}
          />
        ) : null}
      </div>
      <div className="relative mt-1 h-3 text-[10px] text-[var(--color-muted)]">
        <span className="absolute -translate-x-1/2" style={{ left: `${pct(g.breakeven)}%` }}>
          {money(g.breakeven)}
        </span>
        <span
          className="absolute -translate-x-1/2"
          style={{ left: `${pct(g.shortLeg)}%`, color: PROFIT }}
        >
          {money(g.shortLeg)}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-3 text-[10px] text-[var(--color-muted)]">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: PROFIT }} />
          max profit
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: `${LOSS}3a` }} />
          loss
        </span>
        <span className="ml-auto">break-even ↑ · target {money(g.shortLeg)}</span>
      </div>
    </div>
  );
}

function DriftPlainEnglish({ g, trade }: { g: DriftGeo; trade: PaperTrade }) {
  const exp = fmtDate(trade.expiration);
  const dirWord = g.long ? "rises to" : "falls to";
  const sustain = g.long ? "stays below" : "stays above";
  return (
    <p className="mt-2 text-xs leading-relaxed text-[var(--color-muted)]">
      Make up to{" "}
      <span className="font-semibold" style={{ color: PROFIT }}>{money(g.maxProfit)}</span>{" "}
      if {trade.ticker} {dirWord} <span className="text-white">{money(g.shortLeg)}</span> or
      better by {exp}. Break even at <span className="text-white">{money(g.breakeven)}</span>;
      the full{" "}
      <span className="font-semibold" style={{ color: LOSS }}>{money(g.maxLoss)}</span>{" "}
      loss only if it {sustain} <span className="text-white">{money(g.longLeg)}</span>.
    </p>
  );
}

function OpenCard({ trade }: { trade: PaperTrade }) {
  const dir = DIR_COLOR[trade.direction] ?? "#8a97b1";
  const status = STATUS_COLOR[trade.status] ?? "#8a97b1";
  const strat = strategyMeta(trade.strategy);
  // Earnings = credit-spread payoff (two-sided profit band). Drift = directional
  // debit-spread payoff (one-sided ramp). Waves (single long option) has no
  // spread geometry, so it falls back to the simple summary.
  const g = (trade.strategy ?? "earnings") === "earnings" ? payoffGeometry(trade) : null;
  const dg = trade.strategy === "drift" ? driftGeometry(trade) : null;
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <Link
          href={`/company/${trade.ticker}`}
          className="font-bold text-lg hover:text-[var(--color-accent)]"
        >
          {trade.ticker}
        </Link>
        <div className="flex items-center gap-1.5">
          <Pill text={strat.label} color={strat.color} />
          <Pill text={trade.status} color={status} />
          <Pill text={trade.direction} color={dir} />
        </div>
      </div>
      <div className="text-sm text-[var(--color-muted)] mt-0.5">{trade.structure}</div>

      {g ? (
        <>
          <RiskBoxes maxProfit={g.maxProfit} maxLoss={g.maxLoss} />
          <PayoffBar g={g} />
          <PlainEnglish g={g} trade={trade} />

          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--color-muted)]">
            <span>
              Credit{" "}
              <span className="text-white">${trade.entry_credit?.toFixed(2) ?? "—"}</span>
            </span>
            <span>·</span>
            <span>
              <span className="text-white">{trade.contracts ?? "—"}</span> contract
              {trade.contracts === 1 ? "" : "s"}
            </span>
          </div>
          <Legs trade={trade} />
        </>
      ) : dg ? (
        <>
          {trade.thesis ? (
            <div className="text-xs mt-1" style={{ color: dir }}>
              {trade.thesis}
            </div>
          ) : null}
          <RiskBoxes maxProfit={dg.maxProfit} maxLoss={dg.maxLoss} />
          <DriftPayoffBar g={dg} />
          <DriftPlainEnglish g={dg} trade={trade} />

          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--color-muted)]">
            <span>
              Debit{" "}
              <span className="text-white">${trade.entry_credit?.toFixed(2) ?? "—"}</span>
            </span>
            <span>·</span>
            <span>
              <span className="text-white">{trade.contracts ?? "—"}</span> contract
              {trade.contracts === 1 ? "" : "s"}
            </span>
          </div>
          <Legs trade={trade} />
        </>
      ) : (
        <>
          {trade.thesis ? (
            <div className="text-xs mt-1" style={{ color: dir }}>
              {trade.thesis}
            </div>
          ) : null}
          <Legs trade={trade} />
          <div className="grid grid-cols-3 gap-2 mt-3 text-sm">
            <div>
              <div className="text-[10px] uppercase text-[var(--color-muted)]">
                {(trade.strategy ?? "earnings") === "earnings" ? "Credit" : "Debit"}
              </div>
              <div className="font-semibold">
                ${trade.entry_credit?.toFixed(2) ?? "—"}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-[var(--color-muted)]">
                Contracts
              </div>
              <div className="font-semibold">{trade.contracts ?? "—"}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-[var(--color-muted)]">
                Max risk
              </div>
              <div className="font-semibold">{money(trade.max_risk)}</div>
            </div>
          </div>
        </>
      )}

      <div className="text-[11px] text-[var(--color-muted)] mt-3 flex justify-between">
        <span>Reports {fmtDate(trade.earnings_date)}</span>
        <span>Exp {fmtDate(trade.expiration)}</span>
      </div>
      <div className="text-[10px] text-[var(--color-muted)] mt-1 font-mono">
        {trade.signal_id}
      </div>
    </Card>
  );
}

function Buckets({ title, data }: { title: string; data: Record<string, PaperBucket> }) {
  const rows = Object.entries(data).sort((a, b) => b[1].pnl - a[1].pnl);
  if (!rows.length) return null;
  return (
    <Card className="p-4">
      <h3 className="font-semibold text-sm mb-2">{title}</h3>
      <div className="space-y-1.5">
        {rows.map(([k, b]) => (
          <div key={k} className="flex items-center justify-between text-sm">
            <span className="text-[var(--color-muted)] truncate pr-2">{k}</span>
            <span className="flex items-center gap-2 shrink-0">
              <span className="text-[var(--color-muted)] text-xs">
                {b.wins}/{b.n}
              </span>
              <span className={`font-semibold ${moveClass(b.pnl)}`}>
                {signedMoney(b.pnl)}
              </span>
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function PaperPage() {
  const [data, setData] = useState<PaperResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .paper()
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner label="Loading paper trades…" />;
  if (error || !data) return <EmptyState title="Couldn't load the paper scorecard." />;

  const { stats, account, open, closed } = data;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Paper trader</h1>
        <p className="text-[var(--color-muted)] mt-1 max-w-3xl">
          An autonomous worker runs three strategies on an Alpaca paper account:{" "}
          <span className="text-white">earnings</span> (sell rich IV into a print and
          harvest the crush), <span className="text-white">waves</span> (ride a peer-driven
          drift into a name&apos;s own print), and <span className="text-white">drift</span>{" "}
          (post-earnings announcement drift via a directional debit spread). Each trade is
          sized by conviction and journaled with a unique signal id. This is the live
          scorecard.
        </p>
      </div>

      {!account ? (
        <Card className="p-4 mb-6 border-[#f0a85b]/40">
          <div className="text-sm">
            <span className="font-semibold text-[#f0a85b]">Not connected yet.</span> Add
            your Alpaca <span className="font-mono">paper</span> API key + secret to the
            backend env (<span className="font-mono">ALPACA_API_KEY</span>,{" "}
            <span className="font-mono">ALPACA_API_SECRET</span>) and the worker will
            start placing trades on the next run.
          </div>
        </Card>
      ) : null}

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        <Stat
          label="Account equity"
          value={account ? money(account.equity) : "—"}
          sub={account ? `${money(account.cash)} cash` : "connect Alpaca"}
        />
        <Stat
          label="Realized P&L"
          value={signedMoney(stats.total_pnl)}
          valueClass={moveClass(stats.total_pnl)}
          sub={`${stats.closed_count} closed`}
        />
        <Stat
          label="Win rate"
          value={stats.win_rate !== null ? `${(stats.win_rate * 100).toFixed(0)}%` : "—"}
          sub={`${stats.wins}/${stats.closed_count} wins`}
        />
        <Stat
          label="Open positions"
          value={stats.open_count}
          sub={`${money(stats.open_risk)} at risk`}
        />
        <Stat
          label="Avg / trade"
          value={signedMoney(stats.avg_pnl)}
          valueClass={moveClass(stats.avg_pnl)}
          sub="per closed trade"
        />
      </div>

      <h2 className="font-semibold mb-3">Open positions</h2>
      {open.length ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
          {open.map((t) => (
            <OpenCard key={t.signal_id} trade={t} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="No open positions."
          hint="The worker opens trades when a tracked name reports within the next few days and the playbook flags rich IV."
        />
      )}

      {closed.length ? (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8 mt-8">
            <Buckets title="P&L by structure" data={stats.by_structure} />
            <Buckets title="P&L by direction" data={stats.by_direction} />
            <Buckets title="P&L by conviction" data={stats.by_conviction} />
          </div>

          <h2 className="font-semibold mb-3">Closed trades</h2>
          <Card className="p-4">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[var(--color-muted)] text-xs uppercase tracking-wide">
                    <th className="py-2 pr-4">Ticker</th>
                    <th className="py-2 pr-4">Type</th>
                    <th className="py-2 pr-4">Structure</th>
                    <th className="py-2 pr-4">Reported</th>
                    <th className="py-2 pr-4">Credit</th>
                    <th className="py-2 pr-4">Exit</th>
                    <th className="py-2 pr-4">P&L</th>
                    <th className="py-2 pr-4">Signal</th>
                  </tr>
                </thead>
                <tbody>
                  {closed.map((t) => (
                    <tr key={t.signal_id} className="border-t border-[var(--color-edge)]">
                      <td className="py-2 pr-4 font-semibold">
                        <Link
                          href={`/company/${t.ticker}`}
                          className="hover:text-[var(--color-accent)]"
                        >
                          {t.ticker}
                        </Link>
                      </td>
                      <td className="py-2 pr-4">
                        <Pill text={strategyMeta(t.strategy).label} color={strategyMeta(t.strategy).color} />
                      </td>
                      <td className="py-2 pr-4 text-[var(--color-muted)]">{t.structure}</td>
                      <td className="py-2 pr-4">{fmtDate(t.earnings_date)}</td>
                      <td className="py-2 pr-4">${t.entry_credit?.toFixed(2) ?? "—"}</td>
                      <td className="py-2 pr-4">${t.exit_debit?.toFixed(2) ?? "—"}</td>
                      <td className={`py-2 pr-4 font-semibold ${moveClass(t.realized_pnl)}`}>
                        {signedMoney(t.realized_pnl)}
                      </td>
                      <td className="py-2 pr-4 font-mono text-xs text-[var(--color-muted)]">
                        {t.signal_id}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  );
}
