import Link from "next/link";
import { LeadLag } from "@/lib/api";
import { moveClass, pct, signedPct } from "@/lib/format";

export function PeerWaveList({ peers }: { peers: LeadLag[] }) {
  if (peers.length === 0) {
    return (
      <div className="text-sm text-[var(--color-muted)] py-6 text-center">
        No peer wave history yet. Ingest more themed peers to surface lead-lag signals.
      </div>
    );
  }

  return (
    <div className="divide-y divide-[var(--color-edge)]">
      {peers.map((p) => (
        <div key={p.trigger} className="flex items-center gap-3 py-2.5">
          <Link
            href={`/company/${p.trigger}`}
            className="font-semibold w-16 hover:text-[var(--color-accent)]"
          >
            {p.trigger}
          </Link>
          <div className="flex-1 grid grid-cols-3 gap-2 text-sm">
            <div>
              <span className="text-[var(--color-muted)] text-xs">Avg run-up </span>
              <span className={`font-medium ${moveClass(p.avg_runup_pct)}`}>
                {signedPct(p.avg_runup_pct)}
              </span>
            </div>
            <div>
              <span className="text-[var(--color-muted)] text-xs">Win </span>
              <span className="font-medium">{pct(p.win_rate, 0)}</span>
            </div>
            <div>
              <span className="text-[var(--color-muted)] text-xs">n </span>
              <span className="font-medium">{p.sample_size}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
