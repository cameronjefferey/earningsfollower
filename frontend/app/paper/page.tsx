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

function OpenCard({ trade }: { trade: PaperTrade }) {
  const dir = DIR_COLOR[trade.direction] ?? "#8a97b1";
  const status = STATUS_COLOR[trade.status] ?? "#8a97b1";
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
          <Pill text={trade.status} color={status} />
          <Pill text={trade.direction} color={dir} />
        </div>
      </div>
      <div className="text-sm text-[var(--color-muted)] mt-0.5">{trade.structure}</div>
      {trade.thesis ? (
        <div className="text-xs mt-1" style={{ color: dir }}>
          {trade.thesis}
        </div>
      ) : null}
      <Legs trade={trade} />
      <div className="grid grid-cols-3 gap-2 mt-3 text-sm">
        <div>
          <div className="text-[10px] uppercase text-[var(--color-muted)]">Credit</div>
          <div className="font-semibold">${trade.entry_credit?.toFixed(2) ?? "—"}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-[var(--color-muted)]">Contracts</div>
          <div className="font-semibold">{trade.contracts ?? "—"}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-[var(--color-muted)]">Max risk</div>
          <div className="font-semibold">{money(trade.max_risk)}</div>
        </div>
      </div>
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
          An autonomous worker trades the company-page playbook&apos;s{" "}
          <span className="text-white">premium-selling setups</span> (rich-IV credit
          spreads &amp; iron condors) on an Alpaca paper account: it enters 1–3 days
          before each print, risks ~2% of equity per trade, and closes after the report
          to harvest the IV crush. This is the live scorecard.
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
