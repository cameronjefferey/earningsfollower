"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, EarningsCard, RankedSetup } from "@/lib/api";

type Loadable<T> = { data: T | null; failed: boolean };

interface MarketingData {
  week: Loadable<EarningsCard[]>;
  focus: Loadable<RankedSetup> & { preview: boolean };
}

const Ctx = createContext<MarketingData | null>(null);

/**
 * Fetches the week board and the focus setup ONCE, then shares them with every
 * marketing widget (hero backdrop, board, CTA backdrop, brief peek). Avoids the
 * old behavior of 3–4 uncoordinated calls that could land in different states.
 */
export function MarketingDataProvider({ children }: { children: ReactNode }) {
  const [week, setWeek] = useState<Loadable<EarningsCard[]>>({
    data: null,
    failed: false,
  });
  const [focus, setFocus] = useState<
    Loadable<RankedSetup> & { preview: boolean }
  >({ data: null, failed: false, preview: true });

  useEffect(() => {
    let cancelled = false;

    api
      .earnings("week", undefined, 40)
      .then((res) => {
        if (!cancelled) setWeek({ data: res.cards ?? [], failed: false });
      })
      .catch(() => {
        if (!cancelled) setWeek({ data: null, failed: true });
      });

    api
      .rankedSetups(1)
      .then((r) => {
        if (cancelled) return;
        setFocus({
          data: r.focus ?? r.setups?.[0] ?? null,
          failed: false,
          preview: r.preview ?? true,
        });
      })
      .catch(() => {
        if (!cancelled)
          setFocus({ data: null, failed: true, preview: true });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return <Ctx.Provider value={{ week, focus }}>{children}</Ctx.Provider>;
}

export function useMarketingData(): MarketingData {
  const ctx = useContext(Ctx);
  if (!ctx) {
    return {
      week: { data: null, failed: false },
      focus: { data: null, failed: false, preview: true },
    };
  }
  return ctx;
}
