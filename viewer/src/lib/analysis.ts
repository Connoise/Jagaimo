// Descriptive statistics for the analysis views (F7). These describe past
// behavior only — no predictions, no advice. All functions are pure.

export interface ValuePoint {
  ts: string;
  value: number;
}

/** Simple period-over-period returns: r_t = v_t / v_{t-1} - 1. */
export function simpleReturns(values: number[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < values.length; i++) {
    const prev = values[i - 1];
    out.push(prev === 0 ? 0 : values[i] / prev - 1);
  }
  return out;
}

/** Overall rate of change across the window, as a percent. */
export function rateOfChange(values: number[]): number {
  if (values.length < 2) return NaN;
  const first = values[0];
  const last = values[values.length - 1];
  if (first === 0) return NaN;
  return (last / first - 1) * 100;
}

/** Rolling rate-of-change line (% vs `window` periods ago). */
export function rollingRateOfChange(
  points: ValuePoint[],
  window: number
): ValuePoint[] {
  const out: ValuePoint[] = [];
  for (let i = window; i < points.length; i++) {
    const base = points[i - window].value;
    out.push({
      ts: points[i].ts,
      value: base === 0 ? 0 : (points[i].value / base - 1) * 100,
    });
  }
  return out;
}

export function mean(xs: number[]): number {
  if (xs.length === 0) return NaN;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

/** Sample standard deviation (n-1). */
export function stdev(xs: number[]): number {
  if (xs.length < 2) return NaN;
  const m = mean(xs);
  const v = xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1);
  return Math.sqrt(v);
}

/**
 * Rolling volatility = stdev of returns over a sliding window. Optionally
 * annualized by sqrt(periodsPerYear) if provided.
 */
export function rollingVolatility(
  points: ValuePoint[],
  window: number,
  periodsPerYear?: number
): ValuePoint[] {
  const rets = simpleReturns(points.map((p) => p.value));
  // rets[i] corresponds to points[i+1]
  const out: ValuePoint[] = [];
  for (let i = window; i <= rets.length; i++) {
    const slice = rets.slice(i - window, i);
    let sd = stdev(slice);
    if (periodsPerYear && Number.isFinite(sd)) sd *= Math.sqrt(periodsPerYear);
    out.push({ ts: points[i].ts, value: sd * 100 });
  }
  return out;
}

export interface DrawdownResult {
  maxDrawdownPct: number; // negative number (peak-to-trough), e.g. -23.4
  peakTs: string | null;
  troughTs: string | null;
  /** Underwater curve: % below the running peak at each point. */
  series: ValuePoint[];
}

/** Maximum peak-to-trough decline over the series. */
export function maxDrawdown(points: ValuePoint[]): DrawdownResult {
  let peak = -Infinity;
  let peakTs: string | null = null;
  let worst = 0;
  let worstPeakTs: string | null = null;
  let worstTroughTs: string | null = null;
  const series: ValuePoint[] = [];

  for (const p of points) {
    if (p.value > peak) {
      peak = p.value;
      peakTs = p.ts;
    }
    const dd = peak > 0 ? (p.value / peak - 1) * 100 : 0;
    series.push({ ts: p.ts, value: dd });
    if (dd < worst) {
      worst = dd;
      worstPeakTs = peakTs;
      worstTroughTs = p.ts;
    }
  }
  return {
    maxDrawdownPct: worst,
    peakTs: worstPeakTs,
    troughTs: worstTroughTs,
    series,
  };
}

export interface HistogramBin {
  binStart: number; // percent
  binEnd: number;
  count: number;
  label: string;
}

/** Histogram of returns (expressed as percentages). */
export function returnsHistogram(returns: number[], bins = 21): HistogramBin[] {
  if (returns.length === 0) return [];
  const pct = returns.map((r) => r * 100);
  const min = Math.min(...pct);
  const max = Math.max(...pct);
  if (min === max) {
    return [
      { binStart: min, binEnd: max, count: pct.length, label: min.toFixed(2) },
    ];
  }
  const width = (max - min) / bins;
  const out: HistogramBin[] = Array.from({ length: bins }, (_, i) => ({
    binStart: min + i * width,
    binEnd: min + (i + 1) * width,
    count: 0,
    label: (min + (i + 0.5) * width).toFixed(2),
  }));
  for (const v of pct) {
    let idx = Math.floor((v - min) / width);
    if (idx >= bins) idx = bins - 1;
    if (idx < 0) idx = 0;
    out[idx].count++;
  }
  return out;
}

/**
 * Normalize a series to an index based at `base` (default 100) so series with
 * different price scales can be overlaid and compared (F5).
 */
export function normalizeToIndex(
  points: ValuePoint[],
  base = 100
): ValuePoint[] {
  if (points.length === 0) return [];
  const first = points.find((p) => Number.isFinite(p.value) && p.value !== 0);
  if (!first) return points.map((p) => ({ ts: p.ts, value: NaN }));
  return points.map((p) => ({ ts: p.ts, value: (p.value / first.value) * base }));
}

/** Percent-change series relative to the first point. */
export function toPercentChange(points: ValuePoint[]): ValuePoint[] {
  if (points.length === 0) return [];
  const base = points[0].value;
  return points.map((p) => ({
    ts: p.ts,
    value: base === 0 ? 0 : (p.value / base - 1) * 100,
  }));
}
