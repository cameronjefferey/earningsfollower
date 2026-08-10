// Short, plain-English explanations shown in hover tooltips next to metrics.
export const glossary = {
  implied_move:
    "What the options market expects the stock to move (up OR down) by the first expiry after earnings. Derived from the at-the-money straddle × 0.85 ≈ a 1 standard-deviation move. It's magnitude, not direction.",
  vol_verdict:
    "Implied move vs this stock's own historical average move. Rich = options are pricing a bigger-than-usual move (premium is expensive). Cheap = smaller than usual. In-line = typical.",
  avg_move:
    "Average absolute % move on past earnings (close-to-close, timing-aware). A gauge of how violent this stock's prints usually are.",
  up_rate:
    "Share of past earnings reactions that were positive. A rough directional tilt - 50% is a coin flip.",
  beat_streak:
    "Consecutive quarters the company beat its EPS estimate. Shows consistency, but beats are often already priced in, so it doesn't guarantee an up move.",
  last_move: "The stock's % move on its most recent earnings report.",
  drift:
    "Average cumulative % move over the 5 trading days AFTER the report (post-earnings drift).",
  gap: "Average opening gap on the reaction day vs the prior close.",
  surprise: "EPS actual vs estimate, expressed as a %. Positive = beat, negative = miss.",
  move: "The earnings-day % move, close-to-close, respecting before-open vs after-close timing.",
  expected_runup:
    "How this stock has historically drifted from the peer's report date up to its own print, averaged across past cycles. The 'ride the wave' edge.",
  win_rate: "Share of past cycles where that drift was positive.",
  sample: "Number of past cycles in the calculation - a larger sample is more reliable.",
  vol_edge:
    "How often this stock's actual earnings move reached the move currently priced in by options. A low rate means options look expensive (premium-seller edge); a high rate favors buyers.",
  pead:
    "Post-earnings drift: the average move over the 5 trading days AFTER the report, split by whether the company beat or missed. 'Continuation' is how often that drift kept going in the same direction as the earnings-day move.",
  drift_playbook:
    "Post-earnings announcement drift (PEAD): after a strong print, stocks tend to keep moving the same direction for days. Setups appear here only when the stock beat AND jumped (long) or missed AND dropped (short), its own history shows the drift continued after similar prints, and the price hasn't already broken the earnings-day pivot.",
  drift_hist_edge:
    "This stock's average move over the 5 trading days AFTER past prints similar to the current one (beat + up move for longs, miss + down move for shorts). The 'win' rate is how often that drift continued in the trade's direction.",
  drift_entry_quality:
    "Fresh = drift window just opened (day 0-1), best entry. Still tradeable = some days used, buy pullbacks only. Late = most of the window is gone; only enter on a fresh breakout, sized down.",
  price_target:
    "Consensus analyst price target and its implied upside/downside vs. the current price.",
  analyst_ratings:
    "Current breakdown of analyst ratings (strong buy → strong sell). 'Trend' compares the count of bullish analysts to roughly three months ago.",
  playbook:
    "An explicit, synthesized earnings trade built from this stock's own data: a direction (from price trend, how it reacts to beats, recent prints, post-beat drift, and analyst trend), a volatility stance (sell premium when options look rich vs. realized history, buy when cheap), and a concrete defined-risk options structure with strikes sized to the options-implied expected move. Includes when to put it on, what invalidates it, and the reasoning. Research, not advice.",
} as const;

export type GlossaryKey = keyof typeof glossary;
