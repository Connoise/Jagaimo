import { useMemo, useState } from "react";
import { useTransactions } from "../hooks/useTransactions";
import { num, type TransactionRow, type TxnSide } from "../lib/types";
import {
  formatDate,
  formatDateTime,
  formatPrice,
  formatQty,
  formatUSD,
} from "../lib/format";

const SIDE_PILL: Record<TxnSide, string> = {
  buy: "pill pill-buy",
  sell: "pill pill-sell",
  income: "pill pill-info",
  other: "pill",
};

/**
 * Trade ledger — the historical record of trades/cash events imported by the
 * core (Vanguard CSV transaction sections, Coinbase fills). Read-only here:
 * holdings snapshots stay authoritative for "now"; this answers "what happened".
 */
export function LedgerView() {
  const { data: txns, isLoading, error } = useTransactions();

  const [source, setSource] = useState<string>("all");
  const [side, setSide] = useState<string>("all");
  const [search, setSearch] = useState("");

  const sources = useMemo(
    () => Array.from(new Set((txns ?? []).map((t) => t.source))).sort(),
    [txns]
  );

  const rows = useMemo(() => {
    const q = search.trim().toUpperCase();
    return (txns ?? []).filter(
      (t) =>
        (source === "all" || t.source === source) &&
        (side === "all" || t.side === side) &&
        (!q ||
          (t.symbol ?? "").toUpperCase().includes(q) ||
          (t.description ?? "").toUpperCase().includes(q))
    );
  }, [txns, source, side, search]);

  const totals = useMemo(() => {
    let buys = 0;
    let sells = 0;
    let fees = 0;
    for (const t of rows) {
      const amount = num(t.amount_usd);
      if (Number.isFinite(amount)) {
        if (t.side === "buy") buys += Math.abs(amount);
        if (t.side === "sell") sells += Math.abs(amount);
      }
      const fee = num(t.fees_usd);
      if (Number.isFinite(fee)) fees += fee;
    }
    return { buys, sells, fees };
  }, [rows]);

  return (
    <div className="stack">
      <div className="card">
        <h2 className="m0">Trade ledger</h2>
        <p className="muted">
          A record of trades and cash events imported by the core — Vanguard
          CSV transaction sections and Coinbase fills. Append-only and
          de-duplicated; holdings stay authoritative for what you hold now.
          Vanguard CSVs only carry ~18 months of history.
        </p>
        <div className="row wrap">
          <select
            className="select"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            title="Source"
          >
            <option value="all">all sources</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={side}
            onChange={(e) => setSide(e.target.value)}
            title="Side"
          >
            <option value="all">all sides</option>
            <option value="buy">buy</option>
            <option value="sell">sell</option>
            <option value="income">income</option>
            <option value="other">other</option>
          </select>
          <input
            className="input"
            placeholder="Filter by symbol / description"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <p className="muted">
          {rows.length} transaction{rows.length === 1 ? "" : "s"} · buys{" "}
          {formatUSD(totals.buys)} · sells {formatUSD(totals.sells)} · fees{" "}
          {formatUSD(totals.fees)}
        </p>
      </div>

      <div className="card">
        {isLoading && <p className="muted">Loading…</p>}
        {error != null && <p className="error">Failed: {String(error)}</p>}
        {!isLoading && rows.length === 0 && (
          <p className="muted">
            No transactions yet. They appear after the ingester imports a
            Vanguard CSV export (drop it in VANGUARD_CSV_DIR) or Coinbase
            fills (configure a read-only CDP key).
          </p>
        )}
        {rows.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Source</th>
                <th>Type</th>
                <th>Instrument</th>
                <th className="num">Quantity</th>
                <th className="num">Price</th>
                <th className="num">Amount</th>
                <th className="num">Fees</th>
                <th>Account</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <LedgerRow key={t.txn_id} t={t} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function LedgerRow({ t }: { t: TransactionRow }) {
  const quantity = num(t.quantity);
  const price = num(t.price_usd);
  const amount = num(t.amount_usd);
  const fees = num(t.fees_usd);
  return (
    <tr>
      <td className="nowrap" title={formatDateTime(t.trade_ts)}>
        {formatDate(t.trade_ts)}
      </td>
      <td className="muted">{t.source}</td>
      <td>
        <span className={SIDE_PILL[t.side] ?? "pill"} title={t.description ?? ""}>
          {t.kind ?? t.side}
        </span>
      </td>
      <td>
        <strong>{t.symbol ?? "—"}</strong>
      </td>
      <td className="num">{Number.isFinite(quantity) ? formatQty(quantity) : "—"}</td>
      <td className="num">{Number.isFinite(price) ? formatPrice(price) : "—"}</td>
      <td className="num">{Number.isFinite(amount) ? formatUSD(amount) : "—"}</td>
      <td className="num">{Number.isFinite(fees) && fees !== 0 ? formatUSD(fees) : "—"}</td>
      <td className="muted">{t.account ?? "—"}</td>
    </tr>
  );
}
