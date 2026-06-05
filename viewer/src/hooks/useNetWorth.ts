import { useQuery } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";
import { num, type NetWorth } from "../lib/types";

export interface NetWorthPoint {
  ts: string; // ISO timestamp (UTC)
  total: number; // USD
  anyProblem: boolean;
  bySource: Record<string, number>;
  byAssetClass: Record<string, number>;
}

function mapRow(r: NetWorth): NetWorthPoint {
  const coerce = (o: Record<string, string | number>) =>
    Object.fromEntries(Object.entries(o ?? {}).map(([k, v]) => [k, num(v)]));
  return {
    ts: r.snapshot_ts,
    total: num(r.total_usd),
    anyProblem: r.any_problem,
    bySource: coerce(r.by_source),
    byAssetClass: coerce(r.by_asset_class),
  };
}

async function fetchNetWorth(): Promise<NetWorthPoint[]> {
  const { data, error } = await supabase
    .from("net_worth")
    .select("snapshot_ts,total_usd,by_source,by_asset_class,any_problem")
    .order("snapshot_ts", { ascending: true });
  if (error) throw error;
  return (data as NetWorth[]).map(mapRow);
}

export function useNetWorth() {
  return useQuery({
    queryKey: ["net_worth"],
    queryFn: fetchNetWorth,
    refetchInterval: 60_000, // tracker runs every 15 min; poll modestly
  });
}

/** The earliest snapshot — the honest "tracking since" date (§5). */
export function trackingSince(points: NetWorthPoint[] | undefined): string | null {
  return points && points.length ? points[0].ts : null;
}
