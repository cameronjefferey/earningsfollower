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
import { ReactionEvent } from "@/lib/api";

const UP = "#28c08a";
const DOWN = "#f0556d";

export function ReactionChart({ events }: { events: ReactionEvent[] }) {
  const data = events
    .filter((e) => e.move_pct !== null)
    .map((e) => ({
      date: e.date.slice(0, 7),
      move: (e.move_pct as number) * 100,
      beat: e.beat,
    }));

  if (data.length === 0) {
    return (
      <div className="text-sm text-[var(--color-muted)] py-8 text-center">
        Not enough price history to chart reactions yet.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <XAxis
          dataKey="date"
          tick={{ fill: "#8a97b1", fontSize: 11 }}
          axisLine={{ stroke: "#243049" }}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: "#8a97b1", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip
          cursor={{ fill: "#ffffff08" }}
          contentStyle={{
            background: "#121826",
            border: "1px solid #243049",
            borderRadius: 8,
            color: "#e8edf7",
          }}
          formatter={(v: number) => [`${v.toFixed(1)}%`, "Move"]}
        />
        <ReferenceLine y={0} stroke="#243049" />
        <Bar dataKey="move" radius={[3, 3, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.move >= 0 ? UP : DOWN} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
