import { useQuery } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";
import { num, type Holding } from "../lib/types";

export interface HoldingRow extends Holding {
  quantityN: number;
  priceN: number;
  valueN: number;
}

function mapHolding(h: Holding): HoldingRow {
  return {
    ...h,
    quantityN: num(h.quantity),
    priceN: num(h.price_usd),
    valueN: num(h.value_usd),
  };
}

/** Latest completed snapshot's holdings (the current_holdings view). */
async function fetchCurrentHoldings(): Promise<HoldingRow[]> {
  const { data, error } = await supabase
    .from("current_holdings")
    .select("*")
    .order("value_usd", { ascending: false, nullsFirst: false });
  if (error) throw error;
  return (data as Holding[]).map(mapHolding);
}

export function useCurrentHoldings() {
  return useQuery({
    queryKey: ["current_holdings"],
    queryFn: fetchCurrentHoldings,
    refetchInterval: 60_000,
  });
}

/**
 * Holdings + net worth as of the nearest snapshot at or before `ts` (F3).
 * Returns the resolved snapshot timestamp and its holdings.
 */
async function fetchHoldingsAsOf(ts: string): Promise<{
  snapshotTs: string | null;
  total: number | null;
  holdings: HoldingRow[];
}> {
  // Resolve the nearest snapshot <= ts via the net_worth rollup.
  const { data: nw, error: nwErr } = await supabase
    .from("net_worth")
    .select("snapshot_ts,total_usd")
    .lte("snapshot_ts", ts)
    .order("snapshot_ts", { ascending: false })
    .limit(1);
  if (nwErr) throw nwErr;
  if (!nw || nw.length === 0) return { snapshotTs: null, total: null, holdings: [] };

  const snapshotTs = nw[0].snapshot_ts as string;
  const total = num(nw[0].total_usd as string);

  const { data, error } = await supabase
    .from("holdings")
    .select("*")
    .eq("snapshot_ts", snapshotTs)
    .order("value_usd", { ascending: false, nullsFirst: false });
  if (error) throw error;
  return { snapshotTs, total, holdings: (data as Holding[]).map(mapHolding) };
}

export function useHoldingsAsOf(ts: string | null) {
  return useQuery({
    queryKey: ["holdings_as_of", ts],
    queryFn: () => fetchHoldingsAsOf(ts as string),
    enabled: !!ts,
  });
}
