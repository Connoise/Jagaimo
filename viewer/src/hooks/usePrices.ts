import { useQuery } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";
import { num, type PricePoint } from "../lib/types";
import { windowStartIso, type Timeframe } from "../lib/timeframe";
import type { ValuePoint } from "../lib/analysis";

export type PriceSeries = Record<number, ValuePoint[]>;

/** Per-instrument price series for the given instruments within the window. */
async function fetchPrices(
  instrumentIds: number[],
  tf: Timeframe
): Promise<PriceSeries> {
  if (instrumentIds.length === 0) return {};
  let q = supabase
    .from("prices")
    .select("instrument_id,ts,price_usd")
    .in("instrument_id", instrumentIds)
    .not("price_usd", "is", null)
    .order("ts", { ascending: true });

  const start = windowStartIso(tf);
  if (start) q = q.gte("ts", start);

  const { data, error } = await q;
  if (error) throw error;

  const out: PriceSeries = {};
  for (const id of instrumentIds) out[id] = [];
  for (const row of data as PricePoint[]) {
    (out[row.instrument_id] ??= []).push({
      ts: row.ts,
      value: num(row.price_usd),
    });
  }
  return out;
}

export function usePrices(instrumentIds: number[], tf: Timeframe) {
  const key = [...instrumentIds].sort((a, b) => a - b);
  return useQuery({
    queryKey: ["prices", key, tf],
    queryFn: () => fetchPrices(instrumentIds, tf),
    enabled: instrumentIds.length > 0,
  });
}

/** Latest price per instrument (the latest_prices view) for distance-to-target. */
async function fetchLatestPrices(): Promise<Record<number, number>> {
  const { data, error } = await supabase
    .from("latest_prices")
    .select("instrument_id,price_usd")
    .not("price_usd", "is", null);
  if (error) throw error;
  const out: Record<number, number> = {};
  for (const r of data as PricePoint[]) out[r.instrument_id] = num(r.price_usd);
  return out;
}

export function useLatestPrices() {
  return useQuery({
    queryKey: ["latest_prices"],
    queryFn: fetchLatestPrices,
    refetchInterval: 60_000,
  });
}
