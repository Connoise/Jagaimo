import { useHoldingsAsOf } from "../hooks/useHoldings";
import { useInstrumentMap } from "../hooks/useInstruments";
import { formatDateTime, formatPct, formatUSD } from "../lib/format";

interface Props {
  /** Reference timestamp (ISO), e.g. a pinned point from the chart. */
  pinnedTs: string | null;
  /** Current net worth, for the delta-vs-now comparison. */
  currentTotal: number | null;
  onClear: () => void;
}

/** F3 — holdings + net worth as of the nearest snapshot, with deltas vs now. */
export function PointInTimePanel({ pinnedTs, currentTotal, onClear }: Props) {
  const { data, isLoading } = useHoldingsAsOf(pinnedTs);
  const { map } = useInstrumentMap();

  if (!pinnedTs) {
    return (
      <div className="card">
        <h3>Point-in-time</h3>
        <p className="muted">
          Click a point on the net-worth chart to pin a moment and see holdings
          as of that snapshot.
        </p>
      </div>
    );
  }

  const asOfTotal = data?.total ?? null;
  const delta =
    asOfTotal != null && currentTotal != null ? currentTotal - asOfTotal : null;
  const deltaPct =
    delta != null && asOfTotal ? (delta / asOfTotal) * 100 : null;

  return (
    <div className="card">
      <div className="card-head">
        <h3>As of {formatDateTime(pinnedTs)}</h3>
        <button className="btn-sm" onClick={onClear}>
          clear
        </button>
      </div>
      {isLoading && <p>Loading…</p>}
      {data && data.snapshotTs && (
        <>
          <p className="muted">
            Nearest snapshot: {formatDateTime(data.snapshotTs)}
          </p>
          <div className="stat-row">
            <Stat label="Net worth then" value={formatUSD(asOfTotal ?? NaN)} />
            <Stat
              label="Now"
              value={currentTotal != null ? formatUSD(currentTotal) : "—"}
            />
            <Stat
              label="Change"
              value={
                delta != null
                  ? `${formatUSD(delta)} (${formatPct(deltaPct ?? NaN)})`
                  : "—"
              }
              positive={delta != null ? delta >= 0 : undefined}
            />
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Instrument</th>
                <th>Source</th>
                <th className="num">Value</th>
              </tr>
            </thead>
            <tbody>
              {data.holdings.map((h) => (
                <tr key={h.id}>
                  <td>
                    <strong>{map.get(h.instrument_id)?.symbol ?? h.instrument_id}</strong>
                  </td>
                  <td className="muted">{h.source}</td>
                  <td className="num">
                    {Number.isFinite(h.valueN) ? formatUSD(h.valueN) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {data && !data.snapshotTs && (
        <p className="muted">No snapshot at or before this time.</p>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  positive,
}: {
  label: string;
  value: string;
  positive?: boolean;
}) {
  const color =
    positive === undefined ? undefined : positive ? "#3fb950" : "#f85149";
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ color }}>
        {value}
      </div>
    </div>
  );
}
