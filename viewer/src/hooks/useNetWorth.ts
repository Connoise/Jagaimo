import { useQuery } from "@tanstack/react-query";
import { supabase, type NetWorthRow } from "../lib/supabase";

export interface NetWorthPoint {
  ts: string; // ISO timestamp (UTC)
  total: number; // USD
  anyProblem: boolean;
}

async function fetchNetWorth(): Promise<NetWorthPoint[]> {
  const { data, error } = await supabase
    .from("net_worth")
    .select("snapshot_ts,total_usd,any_problem")
    .order("snapshot_ts", { ascending: true });

  if (error) throw error;

  return (data as NetWorthRow[]).map((r) => ({
    ts: r.snapshot_ts,
    total: Number(r.total_usd),
    anyProblem: r.any_problem,
  }));
}

export function useNetWorth() {
  return useQuery({
    queryKey: ["net_worth"],
    queryFn: fetchNetWorth,
    refetchInterval: 60_000, // tracker runs every 15 min; poll modestly
  });
}
