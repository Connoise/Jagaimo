import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";
import type { Instrument } from "../lib/types";

async function fetchInstruments(): Promise<Instrument[]> {
  const { data, error } = await supabase
    .from("instruments")
    .select("*")
    .order("symbol", { ascending: true });
  if (error) throw error;
  return data as Instrument[];
}

export function useInstruments() {
  return useQuery({ queryKey: ["instruments"], queryFn: fetchInstruments });
}

/** Instruments plus a quick id → Instrument lookup map. */
export function useInstrumentMap() {
  const query = useInstruments();
  const map = useMemo(
    () => new Map((query.data ?? []).map((i) => [i.instrument_id, i])),
    [query.data]
  );
  return { ...query, map };
}

export function instrumentLabel(i: Instrument | undefined): string {
  if (!i) return "—";
  return i.display_name ? `${i.symbol} · ${i.display_name}` : i.symbol;
}
