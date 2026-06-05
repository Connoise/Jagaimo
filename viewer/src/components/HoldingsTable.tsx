import { useMemo, useState } from "react";
import type { HoldingRow } from "../hooks/useHoldings";
import { useInstrumentPrefs, displayLabel } from "../hooks/useInstrumentPrefs";
import type { Instrument } from "../lib/types";
import {
  formatPrice,
  formatQty,
  formatUSD,
  isProblemStatus,
  priceStatusLabel,
} from "../lib/format";

interface Props {
  holdings: HoldingRow[];
  instruments: Map<number, Instrument>;
}

/** V1 — current holdings with price_status labeling + prefs (alias/hide/pin). */
export function HoldingsTable({ holdings, instruments }: Props) {
  const { map: prefs, set } = useInstrumentPrefs();
  const [showHidden, setShowHidden] = useState(false);

  const hiddenCount = holdings.filter(
    (h) => prefs.get(h.instrument_id)?.hidden
  ).length;

  const rows = useMemo(() => {
    const visible = holdings.filter(
      (h) => showHidden || !prefs.get(h.instrument_id)?.hidden
    );
    // Pinned float to the top; otherwise preserve incoming value order.
    return visible
      .map((h, i) => ({ h, i, pinned: !!prefs.get(h.instrument_id)?.pinned }))
      .sort((a, b) => Number(b.pinned) - Number(a.pinned) || a.i - b.i)
      .map((x) => x.h);
  }, [holdings, prefs, showHidden]);

  if (holdings.length === 0) return <p className="muted">No holdings.</p>;

  return (
    <div className="card">
      <div className="card-head">
        <h3>Holdings</h3>
        {hiddenCount > 0 && (
          <button className="btn-sm" onClick={() => setShowHidden((v) => !v)}>
            {showHidden ? "hide" : `show`} {hiddenCount} hidden
          </button>
        )}
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>Instrument</th>
            <th>Source</th>
            <th className="num">Quantity</th>
            <th className="num">Price</th>
            <th className="num">Value</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((h) => {
            const inst = instruments.get(h.instrument_id);
            const pref = prefs.get(h.instrument_id);
            const problem = isProblemStatus(h.price_status);
            const label = displayLabel(inst?.symbol ?? `#${h.instrument_id}`, pref);
            return (
              <tr key={h.id} className={pref?.hidden ? "row-muted" : ""}>
                <td>
                  {pref?.pinned && <span title="Pinned">📌 </span>}
                  <strong>{label}</strong>
                  {inst?.display_name && !pref?.alias && (
                    <span className="muted"> · {inst.display_name}</span>
                  )}
                  {pref?.exclude_from_networth && (
                    <span className="pill" title="Excluded from net worth">
                      excluded
                    </span>
                  )}
                </td>
                <td className="muted">{h.source}</td>
                <td className="num">{formatQty(h.quantityN)}</td>
                <td className="num">
                  {Number.isFinite(h.priceN) ? formatPrice(h.priceN) : "—"}
                </td>
                <td className="num">
                  {Number.isFinite(h.valueN) ? formatUSD(h.valueN) : "—"}
                </td>
                <td>
                  <span className={problem ? "pill pill-warn" : "pill"}>
                    {priceStatusLabel(h.price_status)}
                  </span>
                </td>
                <td className="num nowrap">
                  <button
                    className="btn-sm"
                    title={pref?.pinned ? "Unpin" : "Pin to top"}
                    onClick={() =>
                      set.mutate({
                        instrument_id: h.instrument_id,
                        pinned: !pref?.pinned,
                      })
                    }
                  >
                    {pref?.pinned ? "unpin" : "pin"}
                  </button>{" "}
                  <button
                    className="btn-sm"
                    title={pref?.hidden ? "Unhide" : "Hide from views"}
                    onClick={() =>
                      set.mutate({
                        instrument_id: h.instrument_id,
                        hidden: !pref?.hidden,
                      })
                    }
                  >
                    {pref?.hidden ? "unhide" : "hide"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
