import { useState } from "react";
import { useWatchlist } from "../hooks/useWatchlist";
import { useInstruments } from "../hooks/useInstruments";
import { InstrumentPicker } from "./InstrumentPicker";

/** F5 — watchlist CRUD. Adding an instrument begins pricing it next run. */
export function WatchlistManager() {
  const { data: watchlist, add, remove } = useWatchlist();
  const { data: instruments } = useInstruments();
  const [pick, setPick] = useState<number | null>(null);

  const byId = new Map((instruments ?? []).map((i) => [i.instrument_id, i]));
  const watched = new Set((watchlist ?? []).map((w) => w.instrument_id));
  const addable = (instruments ?? []).filter(
    (i) => !watched.has(i.instrument_id)
  );

  return (
    <div className="card">
      <h3>Watchlist</h3>
      <div className="row">
        <InstrumentPicker
          instruments={addable}
          value={pick}
          onChange={setPick}
          placeholder="Add instrument…"
        />
        <button
          className="btn"
          disabled={pick == null || add.isPending}
          onClick={() => {
            if (pick != null) {
              add.mutate({ instrument_id: pick });
              setPick(null);
            }
          }}
        >
          Add
        </button>
      </div>
      {add.isError && <p className="error">Add failed: {String(add.error)}</p>}

      {watchlist && watchlist.length === 0 && (
        <p className="muted">
          Nothing watched yet. Watched instruments are priced every run even
          when not held.
        </p>
      )}
      <ul className="chip-list">
        {(watchlist ?? []).map((w) => (
          <li key={w.instrument_id} className="chip">
            {byId.get(w.instrument_id)?.symbol ?? `#${w.instrument_id}`}
            <button
              className="chip-x"
              title="Remove"
              onClick={() => remove.mutate(w.instrument_id)}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
