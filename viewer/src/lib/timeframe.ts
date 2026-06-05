// Timeframe model shared by every chart (F1). A timeframe maps to a lookback
// window and, for instruments, an OHLC bar resolution.

export type Timeframe = "hour" | "day" | "week" | "month" | "year" | "all";

export const TIMEFRAMES: Timeframe[] = [
  "hour",
  "day",
  "week",
  "month",
  "year",
  "all",
];

export const TIMEFRAME_LABEL: Record<Timeframe, string> = {
  hour: "1H",
  day: "1D",
  week: "1W",
  month: "1M",
  year: "1Y",
  all: "All",
};

const MS = {
  minute: 60_000,
  hour: 3_600_000,
  day: 86_400_000,
};

const WINDOW_MS: Record<Timeframe, number | null> = {
  hour: MS.hour,
  day: MS.day,
  week: 7 * MS.day,
  month: 30 * MS.day,
  year: 365 * MS.day,
  all: null, // unbounded
};

/** Start of the lookback window, or null for "all". */
export function windowStart(tf: Timeframe, now: Date = new Date()): Date | null {
  const span = WINDOW_MS[tf];
  return span === null ? null : new Date(now.getTime() - span);
}

/** ISO string for the window start, or null. Handy for Supabase `.gte`. */
export function windowStartIso(tf: Timeframe, now: Date = new Date()): string | null {
  const start = windowStart(tf, now);
  return start ? start.toISOString() : null;
}

/** OHLC bar resolution to use for an instrument at this timeframe (F4). */
export function barResolution(tf: Timeframe): "1h" | "1d" {
  return tf === "hour" || tf === "day" ? "1h" : "1d";
}

export interface TimePoint {
  ts: string;
  value: number;
}

/** Keep only points within the timeframe window (ascending input assumed). */
export function filterByWindow<T extends { ts: string }>(
  points: T[],
  tf: Timeframe,
  now: Date = new Date()
): T[] {
  const start = windowStart(tf, now);
  if (!start) return points;
  const cutoff = start.getTime();
  return points.filter((p) => new Date(p.ts).getTime() >= cutoff);
}

export interface Candle {
  ts: string; // bucket open (ISO)
  open: number;
  high: number;
  low: number;
  close: number;
}

/**
 * Derive OHLC candles from a value series by bucketing into fixed intervals
 * (open = first, high = max, low = min, close = last). Used for portfolio
 * candlesticks from intra-period snapshots (F4) — meaningful only at
 * timeframes >= the snapshot interval.
 */
export function resampleToCandles(
  points: TimePoint[],
  bucketMs: number
): Candle[] {
  if (points.length === 0) return [];
  const buckets = new Map<number, TimePoint[]>();
  for (const p of points) {
    const t = new Date(p.ts).getTime();
    const key = Math.floor(t / bucketMs) * bucketMs;
    const arr = buckets.get(key);
    if (arr) arr.push(p);
    else buckets.set(key, [p]);
  }
  return [...buckets.keys()]
    .sort((a, b) => a - b)
    .map((key) => {
      const arr = buckets.get(key)!;
      const values = arr.map((p) => p.value);
      return {
        ts: new Date(key).toISOString(),
        open: values[0],
        high: Math.max(...values),
        low: Math.min(...values),
        close: values[values.length - 1],
      };
    });
}

/** Bucket size (ms) for portfolio candles at a given timeframe. */
export function candleBucketMs(tf: Timeframe): number {
  switch (tf) {
    case "hour":
    case "day":
      return MS.hour; // hourly candles
    case "week":
    case "month":
      return MS.day; // daily candles
    default:
      return 7 * MS.day; // weekly candles for year/all
  }
}
