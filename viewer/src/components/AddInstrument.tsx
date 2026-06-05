import { useState } from "react";
import { useWatchlistRequests } from "../hooks/useWatchlistRequests";
import { formatDateTime } from "../lib/format";

const TICKER_RE = /^[A-Za-z0-9.\-]{1,12}$/;
const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/;

const STATUS_PILL: Record<string, string> = {
  pending: "pill pill-info",
  resolved: "pill",
  error: "pill pill-warn",
};

/**
 * Add a new stock (by ticker) or token (by contract address) to tracking.
 * Holdings are read-only (derived from real balances); this enqueues the
 * instrument so it is priced/charted from the next ingest run on — and shows up
 * automatically in holdings if a connected source ever holds it.
 */
export function AddInstrument() {
  const { data: requests, addEquity, addToken, cancel } = useWatchlistRequests();
  const [kind, setKind] = useState<"equity" | "token">("equity");

  const [ticker, setTicker] = useState("");
  const [address, setAddress] = useState("");
  const [tokenSymbol, setTokenSymbol] = useState("");

  const tickerValid = TICKER_RE.test(ticker.trim());
  const addressValid = ADDRESS_RE.test(address.trim());

  const submit = () => {
    if (kind === "equity") {
      if (!tickerValid) return;
      addEquity.mutate({ symbol: ticker }, { onSuccess: () => setTicker("") });
    } else {
      if (!addressValid) return;
      addToken.mutate(
        { address, symbol: tokenSymbol || undefined },
        {
          onSuccess: () => {
            setAddress("");
            setTokenSymbol("");
          },
        }
      );
    }
  };

  const busy = addEquity.isPending || addToken.isPending;
  const err = addEquity.error || addToken.error;

  return (
    <div className="card">
      <h3>Add instrument</h3>
      <p className="muted">
        Track a new stock or Base token. It’s priced and charted from the next
        run (every 15 min). Holdings stay read-only — derived from your real
        balances.
      </p>

      <div className="segmented" style={{ marginBottom: "0.6rem" }}>
        <button
          className={kind === "equity" ? "seg active" : "seg"}
          onClick={() => setKind("equity")}
        >
          Stock / ETF
        </button>
        <button
          className={kind === "token" ? "seg active" : "seg"}
          onClick={() => setKind("token")}
        >
          Token (Base)
        </button>
      </div>

      {kind === "equity" ? (
        <div className="row">
          <input
            className="input"
            placeholder="Ticker, e.g. NVDA"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
          <button className="btn" disabled={!tickerValid || busy} onClick={submit}>
            Add stock
          </button>
        </div>
      ) : (
        <div className="row wrap">
          <input
            className="input"
            style={{ minWidth: "24rem" }}
            placeholder="Contract address 0x…"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
          />
          <input
            className="input input-sm"
            placeholder="Symbol (optional)"
            value={tokenSymbol}
            onChange={(e) => setTokenSymbol(e.target.value)}
          />
          <button className="btn" disabled={!addressValid || busy} onClick={submit}>
            Add token
          </button>
        </div>
      )}
      {kind === "token" && address && !addressValid && (
        <p className="hint" style={{ color: "var(--warn)" }}>
          Expected 0x followed by 40 hex characters.
        </p>
      )}
      {err && <p className="error">Failed: {String(err)}</p>}

      {requests && requests.length > 0 && (
        <>
          <h4 style={{ marginBottom: "0.4rem" }}>Recent requests</h4>
          <table className="table">
            <tbody>
              {requests.map((r) => (
                <tr key={r.request_id}>
                  <td>
                    <strong>
                      {r.kind === "equity"
                        ? r.symbol
                        : r.symbol ?? `${r.address?.slice(0, 8)}…`}
                    </strong>{" "}
                    <span className="muted">({r.kind})</span>
                  </td>
                  <td>
                    <span className={STATUS_PILL[r.status] ?? "pill"}>
                      {r.status}
                    </span>
                  </td>
                  <td className="muted">{r.detail ?? ""}</td>
                  <td className="muted">{formatDateTime(r.created_at)}</td>
                  <td className="num">
                    {r.status === "pending" && (
                      <button
                        className="btn-sm"
                        onClick={() => cancel.mutate(r.request_id)}
                      >
                        cancel
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
