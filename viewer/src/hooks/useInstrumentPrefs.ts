import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";
import type { InstrumentPref } from "../lib/types";

async function fetchPrefs(): Promise<InstrumentPref[]> {
  const { data, error } = await supabase.from("instrument_prefs").select("*");
  if (error) throw error;
  return data as InstrumentPref[];
}

export type PrefPatch = Partial<
  Pick<InstrumentPref, "hidden" | "alias" | "pinned" | "exclude_from_networth">
>;

/**
 * Curation overlay for instruments (hide / alias / pin / exclude-from-net-worth).
 * Writes the instrument_prefs config table — never the canonical instruments
 * dimension (ingester-owned).
 */
export function useInstrumentPrefs() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["instrument_prefs"], queryFn: fetchPrefs });
  const map = useMemo(
    () => new Map((query.data ?? []).map((p) => [p.instrument_id, p])),
    [query.data]
  );

  const set = useMutation({
    mutationFn: async (args: { instrument_id: number } & PrefPatch) => {
      const { error } = await supabase.from("instrument_prefs").upsert({
        ...args,
        updated_at: new Date().toISOString(),
      });
      if (error) throw error;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["instrument_prefs"] });
      // Net-worth rollup honors exclude_from_networth on the next ingest run;
      // refresh holdings so the table reflects hide/alias/pin immediately.
      qc.invalidateQueries({ queryKey: ["current_holdings"] });
    },
  });

  return { ...query, map, set };
}

/** Effective display label for an instrument given its pref alias. */
export function displayLabel(
  symbol: string,
  pref: InstrumentPref | undefined
): string {
  return pref?.alias?.trim() || symbol;
}
