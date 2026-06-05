import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

export interface LineSpec {
  id: string;
  color: string;
  data: { ts: string; value: number }[];
}

export interface CandleSpec {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface Props {
  lines?: LineSpec[];
  candles?: CandleSpec[];
  height?: number;
  precision?: number;
  /** Fired when the user clicks a point — emits the UNIX-seconds timestamp. */
  onClickTime?: (tsSeconds: number) => void;
}

function toTime(ts: string): UTCTimestamp {
  return Math.floor(new Date(ts).getTime() / 1000) as UTCTimestamp;
}

/** lightweight-charts requires unique, ascending times. */
function uniqueAscending<T extends { time: UTCTimestamp }>(rows: T[]): T[] {
  const seen = new Set<number>();
  const out: T[] = [];
  for (const r of [...rows].sort((a, b) => a.time - b.time)) {
    if (seen.has(r.time)) {
      out[out.length - 1] = r; // last value wins for a duplicated timestamp
      continue;
    }
    seen.add(r.time);
    out.push(r);
  }
  return out;
}

export function SeriesChart({
  lines,
  candles,
  height = 360,
  precision = 2,
  onClickTime,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line" | "Candlestick">[]>([]);
  const clickRef = useRef<typeof onClickTime>(onClickTime);
  clickRef.current = onClickTime;

  // Create the chart once.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#0e1116" },
        textColor: "#c9d1d9",
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "#1c2128" },
        horzLines: { color: "#1c2128" },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
      autoSize: true,
    });
    chartRef.current = chart;

    const handler = (param: { time?: Time }) => {
      if (param.time && typeof param.time === "number" && clickRef.current) {
        clickRef.current(param.time);
      }
    };
    chart.subscribeClick(handler);

    return () => {
      chart.unsubscribeClick(handler);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = [];
    };
  }, []);

  // Rebuild series whenever data changes (handles dynamic overlay counts).
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    for (const s of seriesRef.current) chart.removeSeries(s);
    seriesRef.current = [];

    if (candles && candles.length) {
      const series = chart.addCandlestickSeries({
        upColor: "#3fb950",
        downColor: "#f85149",
        wickUpColor: "#3fb950",
        wickDownColor: "#f85149",
        borderVisible: false,
        priceFormat: { type: "price", precision, minMove: 10 ** -precision },
      });
      series.setData(
        uniqueAscending(
          candles.map((c) => ({
            time: toTime(c.ts),
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
          }))
        )
      );
      seriesRef.current.push(series);
    }

    for (const line of lines ?? []) {
      const series = chart.addLineSeries({
        color: line.color,
        lineWidth: 2,
        priceFormat: { type: "price", precision, minMove: 10 ** -precision },
      });
      series.setData(
        uniqueAscending(
          line.data
            .filter((d) => Number.isFinite(d.value))
            .map((d) => ({ time: toTime(d.ts), value: d.value }))
        )
      );
      seriesRef.current.push(series);
    }

    chart.timeScale().fitContent();
  }, [lines, candles, precision]);

  return <div ref={containerRef} style={{ height, width: "100%" }} />;
}
