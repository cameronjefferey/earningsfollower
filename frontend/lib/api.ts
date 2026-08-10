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

export type ConvictionTier = "low" | "medium" | "high";

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
  /** Playbook-aligned tier; null when history is too thin to score. */
  conviction?: ConvictionTier | null;
}

export interface EarningsResponse {
  window: string;
  start: string;
  end: string;
  theme: string | null;
  cards: EarningsCard[];
  limit?: number;
  count?: number;
  has_more?: boolean;
  updated_at?: string | null;
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

export interface PlayLeg {
  action: "Sell" | "Buy";
  option: "call" | "put";
  label: string;
  strike: number | null;
  note: string;
}

export interface ConvictionBasis {
  vol_stance: string;
  exceed_rate: number | null;
  seller_edge: number | null;
  edge_sample: number;
  richness: number | null;
  dir_score: number;
  data_suspect: boolean;
  tier_reason?: string;
}

export interface EarningsPlay {
  headline: string;
  direction: "bearish" | "bullish" | "neutral";
  conviction: "low" | "medium" | "high";
  conviction_basis: ConvictionBasis;
  vol_stance: "sell" | "buy" | "neutral";
  structure: string;
  structure_detail: string;
  timing: string;
  legs: PlayLeg[];
  expected_range_low: number | null;
  expected_range_high: number | null;
  spot: number | null;
  invalidation: string;
  bias_reasons: string[];
  vol_reasons: string[];
  caveats: string[];
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
  playbook: EarningsPlay | null;
  price_history: PricePoint[];
  /** Live/last trade when available (Alpaca → Yahoo); else omit and use EOD. */
  last_price?: number | null;
  /** Change vs prior session close when last_price is present. */
  day_change_pct?: number | null;
  reactions: { summary: ReactionSummary; events: ReactionEvent[] };
  peers: LeadLag[];
  preview?: boolean;
  preview_note?: string | null;
}

export type SampleTier = "thin" | "ok" | "solid";

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
  sample_tier?: SampleTier;
  win_rate_ci_low?: number | null;
}

export interface WaveWatchItem {
  target: string;
  target_name: string | null;
  target_report_date: string | null;
  peer_count: number;
  ripped_count: number;
  peers: { ticker: string; move_pct: number | null }[];
  themes: string[];
}

export interface WaveWatchResponse {
  count: number;
  waves: WaveWatchItem[];
  updated_at?: string | null;
}

export interface WavesResponse {
  recent_days: number;
  upcoming_days: number;
  limit?: number;
  count: number;
  has_more?: boolean;
  signals: WaveSignal[];
  preview?: boolean;
  preview_note?: string | null;
  updated_at?: string | null;
}

export interface DriftHistory {
  sample_size: number;
  avg_drift_5d_pct: number | null;
  win_rate_5d: number | null;
  avg_drift_10d_pct: number | null;
  win_rate_10d: number | null;
}

export interface DriftLive {
  anchor_date: string;
  anchor_open: number | null;
  anchor_close: number | null;
  last_date: string;
  last_close: number | null;
  drift_so_far_pct: number | null;
  trading_days_in: number;
  trading_days_left: number;
  stop_level: number | null;
}

export interface DriftPlan {
  entry: string;
  exit: string;
  stop: string;
  entry_quality: "fresh" | "ok" | "late";
}

export interface DriftSetup {
  ticker: string;
  name: string | null;
  sector: string | null;
  market_cap: number | null;
  themes: ThemeTag[];
  direction: "long" | "short";
  score: number;
  report_date: string;
  timing: string;
  beat: boolean;
  surprise_pct: number | null;
  revenue_beat: boolean | null;
  move_pct: number | null;
  gap_pct: number | null;
  held_gap: boolean | null;
  history: DriftHistory;
  live: DriftLive;
  /** Present for admins only; stripped for everyone else. */
  plan: DriftPlan | null;
  why: string[];
  sample_tier?: SampleTier;
  win_rate_ci_low?: number | null;
}

export interface DriftResponse {
  lookback_days: number;
  limit?: number;
  count: number;
  has_more?: boolean;
  setups: DriftSetup[];
  preview?: boolean;
  preview_note?: string | null;
  updated_at?: string | null;
}

export interface PaperTradeLeg {
  symbol: string;
  type: "call" | "put";
  side: "buy" | "sell";
  strike: number;
  mid: number;
}

export interface RedditSignal {
  scan_date: string | null;
  ticker: string;
  mention_count: number;
  mention_velocity: number | null;
  score: number | null;
  sentiment: number | null;
  direction: "bullish" | "bearish" | "neutral";
  conviction: "low" | "medium" | "high";
  pump_risk: "low" | "medium" | "high";
  is_noise: boolean;
  scored_by: "llm" | "heuristic";
  rationale: string | null;
  subreddits: string[];
  samples: string[];
}

export interface RedditResponse {
  source: "live" | "journal";
  count: number;
  signals: RedditSignal[];
  preview?: boolean;
  preview_note?: string | null;
}

export interface PaperTrade {
  signal_id: string;
  strategy: "earnings" | "waves" | "drift" | "reddit";
  ticker: string;
  structure: string;
  direction: "bearish" | "bullish" | "neutral";
  conviction: "low" | "medium" | "high";
  status: "pending" | "open" | "closing" | "closed" | "canceled";
  contracts: number | null;
  earnings_date: string | null;
  expiration: string | null;
  width: number | null;
  entry_credit: number | null;
  modeled_credit: number | null;
  exit_debit: number | null;
  max_risk: number | null;
  realized_pnl: number | null;
  expected_move_pct: number | null;
  spot_entry: number | null;
  spot_now: number | null;
  spot_at_exit: number | null;
  realized_move_pct: number | null;
  breached_short: boolean | null;
  outcome: "win" | "loss" | null;
  legs: PaperTradeLeg[];
  thesis: string | null;
  subreddits: string[];
  opened_at: string | null;
  closed_at: string | null;
  note: string | null;
}

export interface PaperBucket {
  n: number;
  pnl: number;
  wins: number;
}

export interface PaperStats {
  open_count: number;
  closed_count: number;
  wins: number;
  win_rate: number | null;
  total_pnl: number;
  avg_pnl: number | null;
  open_risk: number;
  by_structure: Record<string, PaperBucket>;
  by_direction: Record<string, PaperBucket>;
  by_conviction: Record<string, PaperBucket>;
  by_strategy: Record<string, PaperBucket>;
  by_subreddit: Record<string, PaperBucket>;
  by_reddit_instrument: Record<string, PaperBucket>;
}

export interface PaperAccount {
  equity: number | null;
  cash: number | null;
  buying_power: number | null;
  status: string | null;
}

export interface PaperLastRun {
  id: number;
  job: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  opened: number;
  closed: number;
  error_count: number;
  detail: Record<string, unknown> | null;
}

export interface PaperResponse {
  generated_at: string;
  account: PaperAccount | null;
  stats: PaperStats;
  open: PaperTrade[];
  closed: PaperTrade[];
  last_run?: PaperLastRun | null;
  live_stop_policy?: LiveStopPolicy | null;
  live_exit_policy?: LiveExitPolicy | null;
}

export interface AttrCohort {
  key: string;
  n: number;
  wins: number;
  win_rate: number;
  win_rate_ci: [number, number];
  total_pnl: number;
  avg_pnl: number;
  avg_pnl_ci: [number, number] | null;
  avg_win_prob: number | null;
  calibration_gap: number | null;
}

export interface AttrCorr {
  r: number;
  ci: [number, number];
  n: number;
  significant: boolean;
}

export interface AttrTercile {
  band: string;
  range: [number, number];
  n: number;
  win_rate: number;
  avg_pnl: number;
}

export interface AttrNumericFeature {
  feature: string;
  label: string;
  n: number;
  corr_win: AttrCorr | null;
  corr_pnl: AttrCorr | null;
  terciles: AttrTercile[];
}

export interface AttrCalibrationBucket {
  range: [number, number];
  n: number;
  avg_predicted: number;
  realized_win_rate: number;
}

export interface AttrCalibration {
  n: number;
  avg_predicted: number | null;
  realized_win_rate: number | null;
  buckets: AttrCalibrationBucket[];
}

export interface AttrCounterfactualSide {
  n: number;
  avg_fav_move_5d: number;
  up_rate: number;
}

export interface AttrCounterfactual {
  strategy: string;
  opened: AttrCounterfactualSide | null;
  skipped: AttrCounterfactualSide | null;
}

export interface AttrOverall {
  n: number;
  wins: number;
  win_rate: number | null;
  total_pnl: number;
  avg_pnl: number | null;
}

export interface AttributionResponse {
  generated_at: string;
  graded_trades: number;
  overall: AttrOverall;
  min_samples: number;
  cohort_labels: Record<string, string>;
  cohorts: Record<string, AttrCohort[]>;
  numeric_features: AttrNumericFeature[];
  calibration: AttrCalibration;
  counterfactual: AttrCounterfactual[];
  notes: string[];
}

export interface NarrativeSection {
  title: string;
  points: string[];
}

export interface CalibrationStrategy {
  strategy: string;
  n: number;
  predicted: number;
  realized: number;
  multiplier: number;
  applicable: boolean;
}

export interface CalibrationState {
  enabled: boolean;
  min_samples: number;
  max_delta: number;
  strategies: CalibrationStrategy[];
}

export interface NarrativeResponse {
  source: "llm" | "heuristic" | "empty";
  generated_at: string;
  headline: string;
  sections: NarrativeSection[];
  hypotheses: string[];
  caveats: string[];
  calibration: CalibrationState;
  live_stop_policy?: LiveStopPolicy | null;
  live_exit_policy?: LiveExitPolicy | null;
}

export interface WeekCumulative {
  graded_trades: number;
  win_rate: number | null;
  avg_pnl: number | null;
  total_pnl: number;
  calibration_gap: number | null;
  significant_features: number;
}

export interface WeekNew {
  closed: number;
  wins: number;
  win_rate: number | null;
  avg_pnl: number | null;
  total_pnl: number;
}

export interface WeekDeltas {
  win_rate: number | null;
  calibration_gap: number | null;
  avg_pnl: number | null;
  graded_trades: number;
  significant_features: number;
}

export interface ProgressWeek {
  label: string;
  week_start: string;
  week_end: string;
  cumulative: WeekCumulative;
  new_this_week: WeekNew;
  changes: string[];
  improvement_score: number;
  status: "improved" | "regressed" | "flat";
  deltas: WeekDeltas | null;
}

export interface ProgressVerdict {
  learning: boolean | null;
  weeks_improved?: number;
  weeks_regressed?: number;
  calibration_gap_trend?: number | null;
  win_rate_trend?: number | null;
  summary: string;
}

export interface ProgressResponse {
  generated_at: string;
  weeks: ProgressWeek[];
  verdict: ProgressVerdict;
}

export interface SignalGroup {
  n: number;
  hit_rate: number;
  hit_rate_ci: [number, number];
  avg_fav_move_5d: number;
  avg_fav_move_5d_ci: [number, number] | null;
  avg_fav_move_1d: number | null;
  n_excess: number;
  avg_excess_move_5d: number | null;
  avg_excess_move_5d_ci: [number, number] | null;
  beat_rate: number | null;
  beat_rate_ci: [number, number] | null;
}

export interface MarketBaseline {
  n: number;
  avg_excess_move_5d: number;
  avg_excess_move_5d_ci: [number, number] | null;
  beat_rate: number | null;
  significant: boolean;
}

export interface SignalCohort extends SignalGroup {
  key: string;
}

export interface ExecEntryTiming {
  n: number;
  median_lag_days: number | null;
  avg_pre_entry_fav_move: number | null;
  chased_rate: number | null;
  chased_threshold: number;
}

export interface ExecCaptureRow {
  signal_id: string | null;
  ticker: string;
  strategy: string;
  mfe: number;
  mae: number;
  realized_fav_move: number;
  gave_back: number;
  capture_ratio: number | null;
  hold_days: number | null;
}

export interface ExecCaptureSummary {
  n: number;
  median_capture_ratio: number | null;
  avg_capture_ratio: number | null;
  avg_mfe: number | null;
  avg_mae: number | null;
  left_on_table_rate: number | null;
  avg_hold_days: number | null;
}

export interface ExitPolicy {
  label: string;
  avg_captured: number;
  median_captured: number;
  win_rate: number;
  params: Record<string, number>;
  lift_vs_actual: number | null;
}

export interface ExecSignalWeek {
  label: string;
  week_start: string;
  n: number;
  hit_rate: number | null;
  avg_fav_move_5d: number | null;
  avg_excess_move_5d: number | null;
}

export interface ExecutionResponse {
  generated_at: string;
  graded_signals: number;
  min_samples: number;
  market_baseline: MarketBaseline | null;
  signal_quality: {
    overall: SignalGroup | null;
    by_strategy: SignalCohort[];
    by_conviction: SignalCohort[];
    opened_vs_skipped: {
      opened: SignalGroup | null;
      skipped: SignalGroup | null;
    };
  };
  entry_timing: ExecEntryTiming;
  exit_capture: {
    summary: ExecCaptureSummary;
    played_out: ExecCaptureSummary;
    mfe_hurdle: number;
    worst_giveback: ExecCaptureRow[];
    graded: number;
  };
  exit_policy: {
    n: number;
    policies: ExitPolicy[];
    best: ExitPolicy | null;
  };
  live_exit_policy: LiveExitPolicy | null;
  live_stop_policy?: LiveStopPolicy | null;
  signal_weeks: ExecSignalWeek[];
  notes: string[];
}

export interface LiveExitPolicy {
  enabled: boolean;
  learning_enabled: boolean;
  default_pct: number;
  effective_pct: number;
  band: [number, number];
  min_samples: number;
  learned: {
    take_profit_pct: number;
    n: number;
    avg_captured: number;
    actual_avg_captured: number;
    lift: number;
    applicable: boolean;
    source: string;
  } | null;
}

export interface LiveStopPolicy {
  enabled: boolean;
  stop_loss_frac: number;
  late_dte: number;
  late_stop_frac: number;
  applies_to: string;
  note: string;
}

async function authHeaders(accessToken?: string | null): Promise<HeadersInit> {
  // Only attach a bearer when the caller already resolved one via useAuthReady.
  // Do NOT call getSession() here - that hits /api/auth/session on every public
  // fetch and can thrash the Next.js dev server.
  if (accessToken) {
    return { Authorization: `Bearer ${accessToken}` };
  }
  return {};
}

async function getJSON<T>(path: string, accessToken?: string | null): Promise<T> {
  const headers = await authHeaders(accessToken);
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", headers });
  if (!res.ok) {
    if (res.status === 401 || res.status === 402) {
      throw new Error(
        res.status === 401
          ? "Sign in required for this data"
          : "Active subscription required"
      );
    }
    throw new Error(`API ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface TrackRecordBucket {
  key: string;
  n: number;
  win_rate: number | null;
  win_rate_ci_low: number | null;
  sample_tier: SampleTier;
  total_pnl: number | null;
}

export interface TrackRecordResponse {
  generated_at: string;
  preview?: boolean;
  preview_note?: string | null;
  window_note?: string;
  overall: {
    closed_count: number;
    wins: number;
    win_rate: number | null;
    win_rate_ci_low: number | null;
    sample_tier: SampleTier;
    total_pnl: number | null;
    avg_pnl: number | null;
  };
  by_strategy: TrackRecordBucket[];
}

export interface DigestBullet {
  kind: string;
  text: string;
}

export interface DigestResponse {
  date: string;
  generated_at: string | null;
  preview?: boolean;
  preview_note?: string | null;
  bullets: DigestBullet[];
  updated_at?: string | null;
}

export interface SetupPlan {
  thesis: string;
  trigger_status: string;
  target: string;
  window: string;
  invalidation: string;
  sizing: string;
}

export interface ClusterPeer {
  ticker: string;
  name: string | null;
  edge_pct?: number | null;
  win_rate?: number | null;
  sample_size?: number | null;
  href?: string;
}

export interface RankedSetup {
  id: string;
  rank: number;
  kind: "wave" | "drift";
  ticker: string;
  name: string | null;
  direction: string;
  headline: string;
  action?: string;
  score: number;
  conviction?: number;
  conviction_label?: string;
  trigger?: string | null;
  trigger_move_pct?: number | null;
  trigger_beat?: boolean | null;
  cluster_size?: number;
  cluster_peers?: ClusterPeer[];
  plan?: SetupPlan;
  sample_tier?: SampleTier;
  sample_size?: number;
  win_rate?: number | null;
  win_rate_ci_low?: number | null;
  edge_pct?: number | null;
  report_date?: string | null;
  themes: ThemeTag[];
  why: string[];
  watch: string;
  invalidation: string;
  href: string;
  board_href?: string;
}

export interface BoardQuality {
  count: number;
  solid: number;
  ok: number;
  thin: number;
  distinct_drivers: number;
  median_win_floor?: number | null;
  best_edge_pct?: number | null;
  top_conviction?: number | null;
}

export interface RankedSetupsResponse {
  generated_at: string;
  as_of: string;
  updated_at?: string | null;
  count: number;
  setups: RankedSetup[];
  focus?: RankedSetup | null;
  preview?: boolean;
  preview_note?: string | null;
}

export interface BriefTodayEarnings {
  ticker: string;
  name: string | null;
  timing: string | null;
  implied_move_pct: number | null;
  themes: ThemeTag[];
}

export interface MorningBriefResponse {
  generated_at: string;
  as_of: string;
  preview?: boolean;
  preview_note?: string | null;
  focus?: RankedSetup | null;
  board_quality?: BoardQuality;
  digest: {
    date?: string | null;
    bullets: DigestBullet[];
    updated_at?: string | null;
  };
  ranked: RankedSetup[];
  today_earnings: BriefTodayEarnings[];
  updated_at?: string | null;
}

export const api = {
  themes: () => getJSON<Theme[]>("/themes"),
  earnings: (window: string, theme?: string, limit = 80) =>
    getJSON<EarningsResponse>(
      `/earnings?window=${window}${theme ? `&theme=${theme}` : ""}&limit=${limit}`
    ),
  company: (ticker: string, accessToken?: string | null) =>
    getJSON<CompanyDetail>(`/company/${encodeURIComponent(ticker)}`, accessToken),
  waves: (
    recentDays = 14,
    upcomingDays = 21,
    limit = 40,
    accessToken?: string | null
  ) =>
    getJSON<WavesResponse>(
      `/waves?recent_days=${recentDays}&upcoming_days=${upcomingDays}&limit=${limit}`,
      accessToken
    ),
  waveWatch: () => getJSON<WaveWatchResponse>("/waves/watch"),
  drift: (lookbackDays = 12, limit = 30, accessToken?: string | null) =>
    getJSON<DriftResponse>(
      `/drift?lookback_days=${lookbackDays}&limit=${limit}`,
      accessToken
    ),
  reddit: (refresh = false, accessToken?: string | null) =>
    getJSON<RedditResponse>(`/reddit?refresh=${refresh}`, accessToken),
  trackRecord: (accessToken?: string | null) =>
    getJSON<TrackRecordResponse>("/track-record", accessToken),
  digestToday: (accessToken?: string | null) =>
    getJSON<DigestResponse>("/digest/today", accessToken),
  rankedSetups: (limit = 12, accessToken?: string | null) =>
    getJSON<RankedSetupsResponse>(
      `/setups/ranked?limit=${limit}`,
      accessToken
    ),
  morningBrief: (accessToken?: string | null) =>
    getJSON<MorningBriefResponse>("/brief/today", accessToken),
  paper: (accessToken?: string | null) =>
    getJSON<PaperResponse>("/paper", accessToken),
  paperAttribution: (minSamples = 5, accessToken?: string | null) =>
    getJSON<AttributionResponse>(
      `/paper/attribution?min_samples=${minSamples}`,
      accessToken
    ),
  paperNarrative: (accessToken?: string | null) =>
    getJSON<NarrativeResponse>("/paper/narrative", accessToken),
  paperExecution: (minSamples = 5, weeks = 8, accessToken?: string | null) =>
    getJSON<ExecutionResponse>(
      `/paper/execution?min_samples=${minSamples}&weeks=${weeks}`,
      accessToken
    ),
  paperProgress: (weeks = 8, accessToken?: string | null) =>
    getJSON<ProgressResponse>(`/paper/progress?weeks=${weeks}`, accessToken),
};
