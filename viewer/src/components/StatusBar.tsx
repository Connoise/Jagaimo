import { useQueryClient } from "@tanstack/react-query";
import { useNetWorth } from "../hooks/useNetWorth";
import { formatTimeAgo } from "../lib/format";

// The tracker snapshots every 15 min; flag the data as stale past ~2 cycles,
// which usually means cron stopped.
const STALE_MS = 35 * 60 * 1000;

/** Last-updated indicator + manual refresh (basic affordances). */
export function StatusBar() {
  const qc = useQueryClient();
  const { data, isFetching } = useNetWorth();
  const latest = data && data.length ? data[data.length - 1] : undefined;
  const ageMs = latest ? Date.now() - new Date(latest.ts).getTime() : Infinity;
  const stale = ageMs > STALE_MS;

  return (
    <div className="statusbar">
      {latest ? (
        <span className={stale ? "status-stale" : "muted"} title={latest.ts}>
          {stale ? "⚠ " : ""}updated {formatTimeAgo(latest.ts)}
        </span>
      ) : (
        <span className="muted">no snapshots yet</span>
      )}
      <button
        className="btn-sm"
        disabled={isFetching}
        onClick={() => qc.invalidateQueries()}
        title="Refresh all data"
      >
        {isFetching ? "refreshing…" : "↻ refresh"}
      </button>
    </div>
  );
}
