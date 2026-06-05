import { describe, it, expect } from "vitest";
import {
  simpleReturns,
  rateOfChange,
  stdev,
  maxDrawdown,
  returnsHistogram,
  normalizeToIndex,
  toPercentChange,
  type ValuePoint,
} from "../analysis";
import { resampleToCandles, filterByWindow, barResolution } from "../timeframe";

const vp = (vals: number[]): ValuePoint[] =>
  vals.map((v, i) => ({ ts: new Date(2026, 0, 1, i).toISOString(), value: v }));

describe("analysis", () => {
  it("simpleReturns", () => {
    const r = simpleReturns([100, 110, 99]);
    expect(r[0]).toBeCloseTo(0.1, 5);
    expect(r[1]).toBeCloseTo(-0.1, 5);
  });

  it("rateOfChange overall percent", () => {
    expect(rateOfChange([100, 150])).toBeCloseTo(50, 5);
    expect(rateOfChange([200, 100])).toBeCloseTo(-50, 5);
  });

  it("stdev sample", () => {
    expect(stdev([2, 4, 4, 4, 5, 5, 7, 9])).toBeCloseTo(2.138, 2);
  });

  it("maxDrawdown peak-to-trough", () => {
    const dd = maxDrawdown(vp([100, 120, 80, 90, 130]));
    // peak 120 -> trough 80 = -33.33%
    expect(dd.maxDrawdownPct).toBeCloseTo(-33.333, 2);
    expect(dd.series).toHaveLength(5);
  });

  it("normalizeToIndex bases at 100", () => {
    const n = normalizeToIndex(vp([50, 75, 100]));
    expect(n[0].value).toBe(100);
    expect(n[1].value).toBe(150);
    expect(n[2].value).toBe(200);
  });

  it("toPercentChange from first point", () => {
    const p = toPercentChange(vp([200, 220, 180]));
    expect(p[0].value).toBe(0);
    expect(p[1].value).toBeCloseTo(10, 5);
    expect(p[2].value).toBeCloseTo(-10, 5);
  });

  it("returnsHistogram buckets", () => {
    const h = returnsHistogram([-0.1, 0, 0.1, 0.1], 4);
    const total = h.reduce((a, b) => a + b.count, 0);
    expect(total).toBe(4);
  });
});

describe("timeframe", () => {
  it("resampleToCandles open/high/low/close", () => {
    const points = [
      { ts: new Date(2026, 0, 1, 0, 0).toISOString(), value: 10 },
      { ts: new Date(2026, 0, 1, 0, 20).toISOString(), value: 15 },
      { ts: new Date(2026, 0, 1, 0, 40).toISOString(), value: 8 },
    ];
    const candles = resampleToCandles(points, 3_600_000); // 1h bucket
    expect(candles).toHaveLength(1);
    expect(candles[0]).toMatchObject({ open: 10, high: 15, low: 8, close: 8 });
  });

  it("filterByWindow keeps recent points", () => {
    const now = new Date(2026, 0, 10);
    const points = [
      { ts: new Date(2026, 0, 1).toISOString(), value: 1 },
      { ts: new Date(2026, 0, 9).toISOString(), value: 2 },
    ];
    const kept = filterByWindow(points, "week", now);
    expect(kept.map((p) => p.value)).toEqual([2]);
  });

  it("barResolution maps timeframe to bar size", () => {
    expect(barResolution("hour")).toBe("1h");
    expect(barResolution("day")).toBe("1h");
    expect(barResolution("week")).toBe("1d");
    expect(barResolution("all")).toBe("1d");
  });
});
