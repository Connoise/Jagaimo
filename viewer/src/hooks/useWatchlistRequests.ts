import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";
import type { WatchlistRequest } from "../lib/types";

async function fetchRequests(): Promise<WatchlistRequest[]> {
  const { data, error } = await supabase
    .from("watchlist_requests")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(50);
  if (error) throw error;
  return data as WatchlistRequest[];
}

export interface NewEquityRequest {
  symbol: string;
  note?: string;
}
export interface NewTokenRequest {
  address: string;
  symbol?: string;
  chain?: string;
  note?: string;
}

/**
 * Enqueue a request to start tracking a new stock or token. The ingester
 * resolves it into an instrument + watchlist entry on its next run.
 */
export function useWatchlistRequests() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["watchlist_requests"],
    queryFn: fetchRequests,
    // Poll so the status flips to resolved/error after the next ingest run.
    refetchInterval: 30_000,
  });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["watchlist_requests"] });
    qc.invalidateQueries({ queryKey: ["watchlist"] });
  };

  const addEquity = useMutation({
    mutationFn: async (r: NewEquityRequest) => {
      const { error } = await supabase.from("watchlist_requests").insert({
        kind: "equity",
        symbol: r.symbol.trim().toUpperCase(),
        note: r.note ?? null,
      });
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  const addToken = useMutation({
    mutationFn: async (r: NewTokenRequest) => {
      const { error } = await supabase.from("watchlist_requests").insert({
        kind: "token",
        address: r.address.trim().toLowerCase(),
        symbol: r.symbol?.trim() || null,
        chain: r.chain?.trim().toLowerCase() || "base",
        note: r.note ?? null,
      });
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  const cancel = useMutation({
    mutationFn: async (request_id: number) => {
      const { error } = await supabase
        .from("watchlist_requests")
        .delete()
        .eq("request_id", request_id);
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  return { ...query, addEquity, addToken, cancel };
}
