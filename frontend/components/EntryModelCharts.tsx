"use client";

import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AttrNumericFeature, EntryModelState } from "@/lib/api";
import { Card, Stat } from "./ui";
import { InfoTip } from "./InfoTip";

const PROFIT = "#28c08a";
const LOSS = "#f0556d";
const ACCENT = "#5b8cff";
const MUTED = "#8a97b1";

function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return `${(v * 100).toFixed(digits)}%`;
}

function WeightTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: { label: string; weight: number } }>;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  return (
    <div className="rounded-lg border border-[var(--color-edge)] bg-[#121826] px-3 py-2 text-xs text-[#e8edf7] shadow-xl">
      <div className="font-semibold">{row.label}</div>
      <div style={{ color: row.weight >= 0 ? PROFIT : LOSS }}>
        {row.weight >= 0 ? "helps wins" : "hurts wins"} · weight{" "}
        {row.weight > 0 ? "+" : ""}
        {row.weight.toFixed(2)}
      </div>
    </div>
  );
}

function TercileTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ dataKey?: string; value?: number; color?: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-[var(--color-edge)] bg-[#121826] px-3 py-2 text-xs text-[#e8edf7] shadow-xl">
      <div className="mb-1 font-semibold">{label}</div>
      {payload.map((p) => (
        <div key={String(p.dataKey)} style={{ color: p.color }}>
          {p.dataKey} {pct(p.value, 0)} win
        </div>
      ))}
    </div>
  );
}

export function EntryModelCharts({
  model,
  features,
}: {
  model: EntryModelState | null | undefined;
  features: AttrNumericFeature[] | null | undefined;
}) {
  if (!model && !features?.length) return null;

  const live = Boolean(model?.enabled && model?.applicable);
  const weights = [...(model?.coefficients ?? [])]
    .filter((c) => Number.isFinite(c.weight) && Math.abs(c.weight) >= 0.02)
    .sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight))
    .slice(0, 12)
    .reverse();

  const tercileRows = (features ?? [])
    .filter((f) => f.terciles.length === 3)
    .sort(
      (a, b) =>
        Math.abs(b.corr_pnl?.r ?? 0) - Math.abs(a.corr_pnl?.r ?? 0)
    )
    .slice(0, 8)
    .map((f) => {
      const byBand = Object.fromEntries(f.terciles.map((t) => [t.band, t]));
      return {
        label: f.label,
        low: byBand.low?.win_rate ?? null,
        mid: byBand.mid?.win_rate ?? null,
        high: byBand.high?.win_rate ?? null,
      };
    });

  if (!weights.length && !tercileRows.length && !model) return null;

  const statusColor = live ? PROFIT : MUTED;
  const statusLabel = live ? "on" : model?.enabled ? "warming up" : "off";
  const barH = Math.max(160, weights.length * 28 + 24);

  return (
    <div className="mb-8 space-y-4">
      <Card className="p-4">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">
              What the model is weighing
              <InfoTip text="Logistic weights from closed paper trades. Positive = that factor historically lined up with winners. The model refits every run. Sparse factors drop out until the sample is thick enough." />
            </h2>
            <p className="mt-1 max-w-2xl text-sm text-[var(--color-muted)] leading-relaxed">
              Joint fit on size, implied vs realized vol, earnings history,
              analyst positioning, trend, and days-to-print — then it vetoes
              names it scores poorly before the usual gates.
            </p>
          </div>
          <div className="text-right">
            <div className="text-xl font-semibold" style={{ color: statusColor }}>
              {statusLabel}
            </div>
            <div className="text-xs text-[var(--color-muted)]">
              {live
                ? `${model?.n ?? 0} closed · out-of-sample ${
                    model?.cv_auc != null ? model.cv_auc.toFixed(2) : "-"
                  }`
                : model?.reason || "not enough closed trades yet"}
            </div>
          </div>
        </div>

        {model ? (
          <div className="mb-4 grid gap-2 sm:grid-cols-3">
            <Stat
              label="Closed sample"
              value={`${model.n}`}
              sub={
                model.n_wins != null && model.n_losses != null
                  ? `${model.n_wins} wins · ${model.n_losses} losses`
                  : "from the paper book"
              }
            />
            <Stat
              label="Out-of-sample AUC"
              value={model.cv_auc != null ? model.cv_auc.toFixed(2) : "-"}
              valueClass={
                model.cv_auc != null && model.cv_auc >= 0.52
                  ? "text-[#28c08a]"
                  : ""
              }
              sub="Must clear 0.52 before it can veto"
              info="Chance a random winner scores higher than a random loser. 0.50 is a coin flip."
            />
            <Stat
              label="Veto floor"
              value={pct(model.min_prob ?? 0.45)}
              sub="Skip names scored below this"
            />
          </div>
        ) : null}

        {weights.length ? (
          <ResponsiveContainer width="100%" height={barH}>
            <BarChart
              data={weights}
              layout="vertical"
              margin={{ top: 4, right: 16, left: 8, bottom: 0 }}
            >
              <XAxis
                type="number"
                tick={{ fill: MUTED, fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={148}
                tick={{ fill: MUTED, fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                cursor={{ fill: "#ffffff08" }}
                content={<WeightTooltip />}
              />
              <ReferenceLine x={0} stroke="#243049" />
              <Bar dataKey="weight" radius={[0, 3, 3, 0]} maxBarSize={14}>
                {weights.map((w) => (
                  <Cell
                    key={w.feature}
                    fill={w.weight >= 0 ? PROFIT : LOSS}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-sm text-[var(--color-muted)]">
            Weights show up once the closed book is thick enough to fit.
          </p>
        )}
      </Card>

      {tercileRows.length ? (
        <Card className="p-4">
          <div className="mb-3">
            <h2 className="text-lg font-semibold tracking-tight">
              Win rate by feature level
              <InfoTip text="For each factor, closed trades are split into low / mid / high thirds. Taller green is a higher win rate in that third. This is the raw journal, not the model weights." />
            </h2>
            <p className="mt-1 max-w-2xl text-sm text-[var(--color-muted)] leading-relaxed">
              Low → mid → high of each factor at entry. If high implied move
              wins less often than low, richness is hurting, not helping.
            </p>
          </div>
          <ResponsiveContainer width="100%" height={Math.max(220, tercileRows.length * 36)}>
            <BarChart
              data={tercileRows}
              layout="vertical"
              margin={{ top: 4, right: 16, left: 8, bottom: 0 }}
            >
              <XAxis
                type="number"
                domain={[0, 1]}
                tick={{ fill: MUTED, fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => `${Math.round(v * 100)}%`}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={148}
                tick={{ fill: MUTED, fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                cursor={{ fill: "#ffffff08" }}
                content={<TercileTooltip />}
              />
              <Bar dataKey="low" name="low" fill={MUTED} maxBarSize={8} radius={[0, 2, 2, 0]} />
              <Bar dataKey="mid" name="mid" fill={ACCENT} maxBarSize={8} radius={[0, 2, 2, 0]} />
              <Bar dataKey="high" name="high" fill={PROFIT} maxBarSize={8} radius={[0, 2, 2, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-2 flex gap-4 text-[11px] text-[var(--color-muted)]">
            <span><span className="inline-block h-2 w-2 rounded-sm mr-1" style={{ background: MUTED }} />low third</span>
            <span><span className="inline-block h-2 w-2 rounded-sm mr-1" style={{ background: ACCENT }} />mid</span>
            <span><span className="inline-block h-2 w-2 rounded-sm mr-1" style={{ background: PROFIT }} />high third</span>
          </div>
        </Card>
      ) : null}
    </div>
  );
}
