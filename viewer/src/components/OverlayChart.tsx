import { useMemo } from "react";
import { usePrices } from "../hooks/usePrices";
import { normalizeToIndex, toPercentChange } from "../lib/analysis";
import type { Timeframe } from "../lib/timeframe";
import type { Instrument } from "../lib/types";
import { SeriesChart, type LineSpec } from "./SeriesChart";

const PALETTE = [
  "#58a6ff",
  "#3fb950",
  "#d29922",
  "#bc8cff",
  "#f778ba",
  "#39c5cf",
  "#ff7b72",
  "#e3b341",
];

interface Props {
  instrumentIds: number[];
  instruments: Map<number, Instrument>;
  tf: Timeframe;
  /** index = base 100; percent = % change from window start (F5). */
  normalize: "index" | "percent";
}

/** F5 — overlay multiple instruments as normalized, comparable traces. */
export function OverlayChart({
  instrumentIds,
  instruments,
  tf,
  normalize,
}: Props) {
  const { data, isLoading, error } = usePrices(instrumentIds, tf);

  const lines: LineSpec[] = useMemo(() => {
    if (!data) return [];
    return instrumentIds.map((id, i) => {
      const raw = data[id] ?? [];
      const norm =
        normalize === "index"
          ? normalizeToIndex(raw, 100)
          : toPercentChange(raw);
      return {
        id: String(id),
        color: PALETTE[i % PALETTE.length],
        data: norm,
      };
    });
  }, [data, instrumentIds, normalize]);

  return (
    <div>
      <div className="legend">
        {instrumentIds.map((id, i) => (
          <span key={id} className="legend-item">
            <span
              className="legend-swatch"
              style={{ background: PALETTE[i % PALETTE.length] }}
            />
            {instruments.get(id)?.symbol ?? `#${id}`}
          </span>
        ))}
      </div>
      {isLoading && <p>Loading…</p>}
      {error && <p className="error">Error: {String(error)}</p>}
      <SeriesChart
        lines={lines}
        precision={normalize === "percent" ? 2 : 2}
      />
      <p className="hint">
        {normalize === "index"
          ? "Indexed to 100 at window start."
          : "Percent change from window start."}
      </p>
    </div>
  );
}
