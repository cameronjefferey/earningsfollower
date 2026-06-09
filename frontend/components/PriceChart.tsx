"use client";

import {
  Area,
  AreaChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PricePoint } from "@/lib/api";

const UP = "#28c08a";
const DOWN = "#f0556d";

function monthTick(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function PriceChart({
  prices,
  earningsDates = [],
}: {
  prices: PricePoint[];
  earningsDates?: string[];
}) {
  if (!prices || prices.length < 2) {
    return (
      <div className="text-sm text-[var(--color-muted)] py-8 text-center">
        Not enough price history to chart yet.
      </div>
    );
  }

  const first = prices[0].close;
  const last = prices[prices.length - 1].close;
  const change = first ? last / first - 1 : 0;
  const color = change >= 0 ? UP : DOWN;

  const lows = prices.map((p) => p.close);
  const min = Math.min(...lows);
  const max = Math.max(...lows);
  const pad = (max - min) * 0.08 || max * 0.05;

  // Only mark earnings prints that fall inside the visible window.
  const byDate = new Map(prices.map((p) => [p.date, p.close]));
  const markers = earningsDates
    .filter((d) => byDate.has(d))
    .map((d) => ({ date: d, close: byDate.get(d) as number }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={prices} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
        <defs>
          <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="date"
          tick={{ fill: "#8a97b1", fontSize: 11 }}
          axisLine={{ stroke: "#243049" }}
          tickLine={false}
          minTickGap={48}
          tickFormatter={monthTick}
        />
        <YAxis
          domain={[min - pad, max + pad]}
          tick={{ fill: "#8a97b1", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={52}
          tickFormatter={(v) => `$${Math.round(v)}`}
        />
        <Tooltip
          cursor={{ stroke: "#243049" }}
          contentStyle={{
            background: "#121826",
            border: "1px solid #243049",
            borderRadius: 8,
            color: "#e8edf7",
          }}
          labelFormatter={(l: string) => monthTick(l)}
          formatter={(v: number) => [`$${v.toFixed(2)}`, "Close"]}
        />
        <Area
          type="monotone"
          dataKey="close"
          stroke={color}
          strokeWidth={2}
          fill="url(#priceFill)"
          isAnimationActive={false}
        />
        {markers.map((m) => (
          <ReferenceDot
            key={m.date}
            x={m.date}
            y={m.close}
            r={4}
            fill="#f0a85b"
            stroke="#0b0f17"
            strokeWidth={1.5}
            isFront
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}
