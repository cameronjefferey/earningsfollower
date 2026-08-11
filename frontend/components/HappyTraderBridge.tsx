/**
 * Outbound bridge to HappyTrader's per-symbol interstitial.
 * HT shows what the EF Alpaca paper bot did in this name (or says it never traded it).
 * Keep "paper" / simulated-money language — never frame as a live track record.
 */
export function happyTraderEarningsUrl(ticker: string): string {
  return `https://happytrader.me/earningsfollower/${encodeURIComponent(
    ticker.trim().toUpperCase()
  )}`;
}

export function HappyTraderBridge({ ticker }: { ticker: string }) {
  const symbol = ticker.trim().toUpperCase();
  if (!symbol) return null;

  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-lg border border-[var(--color-edge)]/60 bg-[var(--color-panel)]/40 px-3 py-2.5">
      <div className="min-w-0">
        <p className="text-sm text-white">
          Paper bot on HappyTrader
        </p>
        <p className="text-xs text-[var(--color-muted)] mt-0.5 leading-snug">
          See what the Alpaca paper account actually did in {symbol} — simulated
          money, not a performance track record.
        </p>
      </div>
      <a
        href={happyTraderEarningsUrl(symbol)}
        target="_blank"
        rel="noopener noreferrer"
        className="shrink-0 text-sm font-medium text-[var(--color-accent)] hover:underline"
      >
        Open {symbol} on HappyTrader →
      </a>
    </div>
  );
}
