import { useQuery } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";
import { num, type OhlcBar } from "../lib/types";
import { barResolution, windowStartIso, type Timeframe } from "../lib/timeframe";

export interface CandleBar {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

async function fetchOhlc(
  instrumentId: number,
  tf: Timeframe
): Promise<CandleBar[]> {
  const resolution = barResolution(tf);
  let q = supabase
    .from("ohlc_bars")
    .select("ts,open,high,low,close")
    .eq("instrument_id", instrumentId)
    .eq("timeframe", resolution)
    .order("ts", { ascending: true });

  const start = windowStartIso(tf);
  if (start) q = q.gte("ts", start);

  const { data, error } = await q;
  if (error) throw error;
  return (data as OhlcBar[]).map((b) => ({
    ts: b.ts,
    open: num(b.open),
    high: num(b.high),
    low: num(b.low),
    close: num(b.close),
  }));
}

export function useOhlc(instrumentId: number | null, tf: Timeframe) {
  return useQuery({
    queryKey: ["ohlc", instrumentId, barResolution(tf), tf],
    queryFn: () => fetchOhlc(instrumentId as number, tf),
    enabled: instrumentId != null,
  });
}
