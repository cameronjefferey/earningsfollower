export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export interface Theme {
  key: string;
  label: string;
  ticker_count: number;
}

export interface ThemeTag {
  key: string;
  label: string;
}

export interface EarningsCard {
  ticker: string;
  name: string | null;
  sector: string | null;
  market_cap: number | null;
  date: string;
  timing: string;
  eps_estimate: number | null;
  eps_actual: number | null;
  reported: boolean;
  themes: ThemeTag[];
  implied_move_pct: number | null;
  implied_verdict: string | null;
  avg_abs_move_pct: number | null;
  up_rate: number | null;
  beat_streak: number;
  last_move_pct: number | null;
}

export interface EarningsResponse {
  window: string;
  start: string;
  end: string;
  theme: string | null;
  cards: EarningsCard[];
}

export interface ReactionEvent {
  date: string;
  timing: string;
  eps_estimate: number | null;
  eps_actual: number | null;
  surprise_pct: number | null;
  beat: boolean | null;
  move_pct: number | null;
  gap_pct: number | null;
  drift_pct: number | null;
  drift_1d_pct: number | null;
  drift_10d_pct: number | null;
}

export interface ReactionSummary {
  sample_size: number;
  avg_abs_move_pct: number | null;
  median_abs_move_pct: number | null;
  avg_move_pct: number | null;
  up_rate: number | null;
  last_move_pct: number | null;
  beat_rate: number | null;
  beat_streak: number;
  avg_move_on_beat_pct: number | null;
  avg_move_on_miss_pct: number | null;
  avg_drift_pct: number | null;
  avg_drift_after_beat_pct: number | null;
  avg_drift_after_miss_pct: number | null;
  continuation_rate: number | null;
}

export interface ImpliedMove {
  expected_move_pct: number | null;
  expiry: string | null;
  underlying_price: number | null;
  atm_strike: number | null;
  straddle_price: number | null;
  historical_avg_abs_move_pct: number | null;
  richness: number | null;
  verdict: string | null;
  computed_at: string | null;
  exceed_rate: number | null;
  edge_verdict: string | null;
  edge_sample: number;
}

export interface Analyst {
  price_target: number | null;
  price_target_high: number | null;
  price_target_low: number | null;
  upside_pct: number | null;
  ratings: {
    strong_buy: number;
    buy: number;
    hold: number;
    sell: number;
    strong_sell: number;
  };
  ratings_total: number;
  bullish_pct: number | null;
  trend: string | null;
  eps_estimate_next: number | null;
  revenue_estimate_next: number | null;
  updated_at: string | null;
}

export interface LeadLag {
  trigger: string;
  target: string;
  sample_size: number;
  avg_runup_pct: number | null;
  win_rate: number | null;
  avg_runup_when_trigger_up_pct: number | null;
  avg_runup_when_trigger_down_pct: number | null;
  score: number;
}

export interface PricePoint {
  date: string;
  close: number;
}

export interface CompanyDetail {
  ticker: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  exchange: string | null;
  market_cap: number | null;
  image: string | null;
  themes: ThemeTag[];
  next_earnings_date: string | null;
  next_earnings_timing: string | null;
  implied_move: ImpliedMove | null;
  analyst: Analyst | null;
  price_history: PricePoint[];
  reactions: { summary: ReactionSummary; events: ReactionEvent[] };
  peers: LeadLag[];
}

export interface WaveSignal {
  trigger: string;
  trigger_name: string | null;
  trigger_report_date: string;
  trigger_move_pct: number | null;
  trigger_beat: boolean | null;
  target: string;
  target_name: string | null;
  target_report_date: string;
  shared_themes: ThemeTag[];
  direction: string;
  expected_runup_pct: number | null;
  stats: LeadLag;
}

export interface WavesResponse {
  recent_days: number;
  upcoming_days: number;
  count: number;
  signals: WaveSignal[];
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  themes: () => getJSON<Theme[]>("/themes"),
  earnings: (window: string, theme?: string) =>
    getJSON<EarningsResponse>(
      `/earnings?window=${window}${theme ? `&theme=${theme}` : ""}`
    ),
  company: (ticker: string) =>
    getJSON<CompanyDetail>(`/company/${encodeURIComponent(ticker)}`),
  waves: (recentDays = 14, upcomingDays = 21) =>
    getJSON<WavesResponse>(
      `/waves?recent_days=${recentDays}&upcoming_days=${upcomingDays}`
    ),
};
