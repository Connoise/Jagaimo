import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";
import type { WatchlistEntry } from "../lib/types";

async function fetchWatchlist(): Promise<WatchlistEntry[]> {
  const { data, error } = await supabase
    .from("watchlist")
    .select("*")
    .order("added_at", { ascending: false });
  if (error) throw error;
  return data as WatchlistEntry[];
}

export function useWatchlist() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["watchlist"], queryFn: fetchWatchlist });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["watchlist"] });

  const add = useMutation({
    mutationFn: async (args: { instrument_id: number; note?: string }) => {
      const { error } = await supabase
        .from("watchlist")
        .upsert({ instrument_id: args.instrument_id, note: args.note ?? null });
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: async (instrument_id: number) => {
      const { error } = await supabase
        .from("watchlist")
        .delete()
        .eq("instrument_id", instrument_id);
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  return { ...query, add, remove };
}
