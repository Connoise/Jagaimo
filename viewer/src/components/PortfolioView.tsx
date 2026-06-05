import { useMemo, useState } from "react";
import { useNetWorth, trackingSince } from "../hooks/useNetWorth";
import { useCurrentHoldings } from "../hooks/useHoldings";
import { useInstrumentMap } from "../hooks/useInstruments";
import {
  candleBucketMs,
  filterByWindow,
  resampleToCandles,
  windowStart,
  type Timeframe,
} from "../lib/timeframe";
import { formatDateTime, formatUSD } from "../lib/format";
import { SeriesChart } from "./SeriesChart";
import { TimeframeSwitcher } from "./TimeframeSwitcher";
import { BreakdownPanel } from "./BreakdownPanel";
import { HoldingsTable } from "./HoldingsTable";
import { PointInTimePanel } from "./PointInTimePanel";

export function PortfolioView() {
  const [tf, setTf] = useState<Timeframe>("month");
  const [mode, setMode] = useState<"line" | "candles">("line");
  const [pinnedTs, setPinnedTs] = useState<string | null>(null);

  const { data: points, isLoading, error } = useNetWorth();
  const holdingsQ = useCurrentHoldings();
  const { map } = useInstrumentMap();

  const windowed = useMemo(
    () => (points ? filterByWindow(points, tf) : []),
    [points, tf]
  );

  const lineData = useMemo(
    () => windowed.map((p) => ({ ts: p.ts, value: p.total })),
    [windowed]
  );

  const candleData = useMemo(
    () =>
      resampleToCandles(
        windowed.map((p) => ({ ts: p.ts, value: p.total })),
        candleBucketMs(tf)
      ),
    [windowed, tf]
  );

  const latest = points && points.length ? points[points.length - 1] : undefined;
  const since = trackingSince(points);

  // §5: if the requested window predates tracking start, say so honestly.
  const start = windowStart(tf);
  const overLong = !!(since && start && new Date(since) > start);

  const onClickTime = (tsSeconds: number) => {
    if (!points || points.length === 0) return;
    const target = tsSeconds * 1000;
    let nearest = points[0];
    let best = Infinity;
    for (const p of points) {
      const d = Math.abs(new Date(p.ts).getTime() - target);
      if (d < best) {
        best = d;
        nearest = p;
      }
    }
    setPinnedTs(nearest.ts);
  };

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <div>
            <h2 className="m0">Net worth</h2>
            {latest && (
              <div className="big-number">{formatUSD(latest.total)}</div>
            )}
          </div>
          <div className="controls">
            <div className="segmented">
              <button
                className={mode === "line" ? "seg active" : "seg"}
                onClick={() => setMode("line")}
              >
                Line
              </button>
              <button
                className={mode === "candles" ? "seg active" : "seg"}
                onClick={() => setMode("candles")}
              >
                Candles
              </button>
            </div>
            <TimeframeSwitcher value={tf} onChange={setTf} />
          </div>
        </div>

        <div className="subhead">
          {since && (
            <span className="muted">tracking since {formatDateTime(since)}</span>
          )}
          {overLong && (
            <span className="pill pill-info">
              showing all available history for this range
            </span>
          )}
          {latest?.anyProblem && (
            <span className="pill pill-warn" title="Some holdings stale/unpriced">
              ⚠ data issues
            </span>
          )}
        </div>

        {isLoading && <p>Loading…</p>}
        {error && <p className="error">Error: {String(error)}</p>}
        {mode === "line" ? (
          <SeriesChart lines={[{ id: "nw", color: "#3fb950", data: lineData }]} onClickTime={onClickTime} />
        ) : (
          <SeriesChart candles={candleData} onClickTime={onClickTime} />
        )}
        <p className="hint">Tip: click the chart to pin a moment in time.</p>
      </div>

      <div className="grid-2">
        <BreakdownPanel
          title="By source"
          breakdown={latest?.bySource ?? {}}
          total={latest?.total ?? 0}
        />
        <BreakdownPanel
          title="By asset class"
          breakdown={latest?.byAssetClass ?? {}}
          total={latest?.total ?? 0}
        />
      </div>

      <PointInTimePanel
        pinnedTs={pinnedTs}
        currentTotal={latest?.total ?? null}
        onClear={() => setPinnedTs(null)}
      />

      {holdingsQ.data && (
        <HoldingsTable holdings={holdingsQ.data} instruments={map} />
      )}
    </div>
  );
}
