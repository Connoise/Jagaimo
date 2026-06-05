import type { HoldingRow } from "../hooks/useHoldings";
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

/** V1 — current holdings with explicit price_status labeling. */
export function HoldingsTable({ holdings, instruments }: Props) {
  if (holdings.length === 0) return <p className="muted">No holdings.</p>;
  return (
    <div className="card">
      <h3>Holdings</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Instrument</th>
            <th>Source</th>
            <th className="num">Quantity</th>
            <th className="num">Price</th>
            <th className="num">Value</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((h) => {
            const inst = instruments.get(h.instrument_id);
            const problem = isProblemStatus(h.price_status);
            return (
              <tr key={h.id}>
                <td>
                  <strong>{inst?.symbol ?? `#${h.instrument_id}`}</strong>
                  {inst?.display_name && (
                    <span className="muted"> · {inst.display_name}</span>
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
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
