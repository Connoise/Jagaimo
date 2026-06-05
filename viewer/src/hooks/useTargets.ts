import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";
import type { PriceTarget, TargetDirection } from "../lib/types";

async function fetchTargets(): Promise<PriceTarget[]> {
  const { data, error } = await supabase
    .from("price_targets")
    .select("*")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return data as PriceTarget[];
}

export interface NewTarget {
  instrument_id: number;
  target_usd: number;
  direction: TargetDirection;
  near_pct?: number;
  label?: string;
}

export function useTargets() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["targets"], queryFn: fetchTargets });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["targets"] });

  const create = useMutation({
    mutationFn: async (t: NewTarget) => {
      const { error } = await supabase.from("price_targets").insert({
        instrument_id: t.instrument_id,
        target_usd: t.target_usd,
        direction: t.direction,
        near_pct: t.near_pct ?? 2.0,
        label: t.label ?? null,
      });
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  const setActive = useMutation({
    mutationFn: async (args: { target_id: number; active: boolean }) => {
      const { error } = await supabase
        .from("price_targets")
        .update({ active: args.active })
        .eq("target_id", args.target_id);
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: async (target_id: number) => {
      const { error } = await supabase
        .from("price_targets")
        .delete()
        .eq("target_id", target_id);
      if (error) throw error;
    },
    onSuccess: invalidate,
  });

  return { ...query, create, setActive, remove };
}

/** Signed distance to target as a percent (positive = price must rise). */
export function distanceToTargetPct(
  price: number,
  target: number
): number {
  if (!Number.isFinite(price) || price === 0) return NaN;
  return (target / price - 1) * 100;
}
