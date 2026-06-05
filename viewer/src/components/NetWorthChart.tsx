import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useNetWorth, type NetWorthPoint } from "../hooks/useNetWorth";

function toSeries(points: NetWorthPoint[]) {
  // lightweight-charts wants unique, ascending UNIX-second timestamps.
  const seen = new Set<number>();
  const out: { time: UTCTimestamp; value: number }[] = [];
  for (const p of points) {
    const t = Math.floor(new Date(p.ts).getTime() / 1000) as UTCTimestamp;
    if (seen.has(t)) continue;
    seen.add(t);
    out.push({ time: t, value: p.total });
  }
  return out;
}

export function NetWorthChart() {
  const { data, isLoading, error } = useNetWorth();
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // Create the chart once.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#0e1116" },
        textColor: "#c9d1d9",
      },
      grid: {
        vertLines: { color: "#1c2128" },
        horzLines: { color: "#1c2128" },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
      autoSize: true,
    });
    chartRef.current = chart;
    seriesRef.current = chart.addLineSeries({
      color: "#3fb950",
      lineWidth: 2,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Push data whenever it changes.
  useEffect(() => {
    if (!seriesRef.current || !data) return;
    seriesRef.current.setData(toSeries(data));
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  const latest = data && data.length ? data[data.length - 1] : undefined;
  const since = data && data.length ? data[0].ts : undefined;

  return (
    <section>
      <header style={{ display: "flex", alignItems: "baseline", gap: "1rem" }}>
        <h2 style={{ margin: 0 }}>Net worth</h2>
        {latest && (
          <span style={{ fontSize: "1.5rem", fontWeight: 600 }}>
            ${latest.total.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </span>
        )}
        {latest?.anyProblem && (
          <span title="Some holdings are stale or unpriced" style={{ color: "#d29922" }}>
            ⚠ data issues
          </span>
        )}
      </header>
      {since && (
        <p style={{ color: "#8b949e", margin: "0.25rem 0 0.75rem" }}>
          tracking since {new Date(since).toLocaleString()}
        </p>
      )}
      {isLoading && <p>Loading…</p>}
      {error && <p style={{ color: "#f85149" }}>Error: {String(error)}</p>}
      <div ref={containerRef} style={{ height: 360, width: "100%" }} />
    </section>
  );
}
