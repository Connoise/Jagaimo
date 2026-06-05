import { useMemo, useState } from "react";
import { useInstrumentMap } from "../hooks/useInstruments";
import type { Timeframe } from "../lib/timeframe";
import { InstrumentChart } from "./InstrumentChart";
import { OverlayChart } from "./OverlayChart";
import { InstrumentPicker } from "./InstrumentPicker";
import { TimeframeSwitcher } from "./TimeframeSwitcher";
import { WatchlistManager } from "./WatchlistManager";
import { AddInstrument } from "./AddInstrument";

/** Instrument path: timeframe (F1), candlesticks (F4), overlays (F5), watchlist. */
export function InstrumentView() {
  const { data: instruments, map } = useInstrumentMap();
  const [selected, setSelected] = useState<number[]>([]);
  const [tf, setTf] = useState<Timeframe>("month");
  const [mode, setMode] = useState<"line" | "candles">("line");
  const [normalize, setNormalize] = useState<"index" | "percent">("index");

  const all = instruments ?? [];
  const primary = selected[0] ?? null;
  const isOverlay = selected.length > 1;

  const addable = useMemo(
    () => all.filter((i) => !selected.includes(i.instrument_id)),
    [all, selected]
  );

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <h2 className="m0">Instruments</h2>
          <div className="controls">
            {!isOverlay && (
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
            )}
            {isOverlay && (
              <div className="segmented">
                <button
                  className={normalize === "index" ? "seg active" : "seg"}
                  onClick={() => setNormalize("index")}
                >
                  Index 100
                </button>
                <button
                  className={normalize === "percent" ? "seg active" : "seg"}
                  onClick={() => setNormalize("percent")}
                >
                  % change
                </button>
              </div>
            )}
            <TimeframeSwitcher value={tf} onChange={setTf} />
          </div>
        </div>

        <div className="row">
          <InstrumentPicker
            instruments={addable}
            value={null}
            onChange={(id) => setSelected((s) => [...s, id])}
            placeholder={selected.length ? "Add to overlay…" : "Select instrument…"}
          />
          <div className="chip-list">
            {selected.map((id) => (
              <span key={id} className="chip">
                {map.get(id)?.symbol ?? `#${id}`}
                <button
                  className="chip-x"
                  onClick={() =>
                    setSelected((s) => s.filter((x) => x !== id))
                  }
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        </div>

        {selected.length === 0 && (
          <p className="muted">
            Pick an instrument to chart it. Add a second to overlay them
            normalized for comparison.
          </p>
        )}

        {isOverlay ? (
          <OverlayChart
            instrumentIds={selected}
            instruments={map}
            tf={tf}
            normalize={normalize}
          />
        ) : primary != null ? (
          <InstrumentChart instrumentId={primary} tf={tf} mode={mode} />
        ) : null}
      </div>

      <AddInstrument />
      <WatchlistManager />
    </div>
  );
}
