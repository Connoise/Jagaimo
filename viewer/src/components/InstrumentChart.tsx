import { usePrices } from "../hooks/usePrices";
import { useOhlc } from "../hooks/useOhlc";
import type { Timeframe } from "../lib/timeframe";
import { SeriesChart } from "./SeriesChart";

interface Props {
  instrumentId: number;
  tf: Timeframe;
  mode: "line" | "candles";
  onClickTime?: (tsSeconds: number) => void;
}

/** F2/F4 — single instrument line (from prices) or candlestick (from ohlc_bars). */
export function InstrumentChart({ instrumentId, tf, mode, onClickTime }: Props) {
  const priceQ = usePrices([instrumentId], tf);
  const ohlcQ = useOhlc(mode === "candles" ? instrumentId : null, tf);

  if (mode === "candles") {
    return (
      <div>
        {ohlcQ.isLoading && <p>Loading…</p>}
        {ohlcQ.error && <p className="error">Error: {String(ohlcQ.error)}</p>}
        {ohlcQ.data && ohlcQ.data.length === 0 && (
          <p className="muted">No OHLC bars for this timeframe yet.</p>
        )}
        <SeriesChart candles={ohlcQ.data ?? []} onClickTime={onClickTime} />
      </div>
    );
  }

  const line = priceQ.data?.[instrumentId] ?? [];
  return (
    <div>
      {priceQ.isLoading && <p>Loading…</p>}
      {priceQ.error && <p className="error">Error: {String(priceQ.error)}</p>}
      {priceQ.data && line.length === 0 && (
        <p className="muted">No price history in this window yet.</p>
      )}
      <SeriesChart
        lines={[{ id: String(instrumentId), color: "#58a6ff", data: line }]}
        onClickTime={onClickTime}
      />
    </div>
  );
}
