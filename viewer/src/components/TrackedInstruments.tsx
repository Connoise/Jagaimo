import { useState } from "react";
import { useInstruments } from "../hooks/useInstruments";
import { useInstrumentPrefs } from "../hooks/useInstrumentPrefs";
import type { Instrument } from "../lib/types";

/**
 * Curate tracked instruments without touching the canonical dimension:
 * rename (alias), hide spam/dust from views, pin favorites, or exclude dust
 * from the net-worth total. All writes go to instrument_prefs (RLS-permitted).
 */
export function TrackedInstruments() {
  const { data: instruments } = useInstruments();
  const { map: prefs, set } = useInstrumentPrefs();
  const [filter, setFilter] = useState("");

  const list = (instruments ?? []).filter((i) => {
    const q = filter.trim().toLowerCase();
    if (!q) return true;
    return (
      i.symbol.toLowerCase().includes(q) ||
      (i.display_name ?? "").toLowerCase().includes(q)
    );
  });

  return (
    <div className="card">
      <div className="card-head">
        <h3>Tracked instruments</h3>
        <input
          className="input input-sm"
          placeholder="Filter…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <p className="muted">
        Rename, hide, pin, or mark as dust (excluded from net worth). These are
        display/curation overrides — the underlying instrument and its history
        are untouched. Exclusions apply to the net-worth total on the next run.
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Alias</th>
            <th className="num">Hidden</th>
            <th className="num">Pinned</th>
            <th className="num">Dust</th>
          </tr>
        </thead>
        <tbody>
          {list.map((inst) => (
            <Row
              key={inst.instrument_id}
              inst={inst}
              hidden={!!prefs.get(inst.instrument_id)?.hidden}
              pinned={!!prefs.get(inst.instrument_id)?.pinned}
              excluded={!!prefs.get(inst.instrument_id)?.exclude_from_networth}
              alias={prefs.get(inst.instrument_id)?.alias ?? ""}
              onSet={(patch) =>
                set.mutate({ instrument_id: inst.instrument_id, ...patch })
              }
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Row({
  inst,
  alias,
  hidden,
  pinned,
  excluded,
  onSet,
}: {
  inst: Instrument;
  alias: string;
  hidden: boolean;
  pinned: boolean;
  excluded: boolean;
  onSet: (patch: {
    alias?: string;
    hidden?: boolean;
    pinned?: boolean;
    exclude_from_networth?: boolean;
  }) => void;
}) {
  const [draft, setDraft] = useState(alias);
  const commitAlias = () => {
    if (draft !== alias) onSet({ alias: draft.trim() || undefined });
  };
  return (
    <tr className={hidden ? "row-muted" : ""}>
      <td>
        <strong>{inst.symbol}</strong>
        {inst.display_name && <span className="muted"> · {inst.display_name}</span>}
      </td>
      <td>
        <input
          className="input input-sm"
          placeholder="(none)"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitAlias}
          onKeyDown={(e) => e.key === "Enter" && commitAlias()}
        />
      </td>
      <td className="num">
        <input
          type="checkbox"
          checked={hidden}
          onChange={(e) => onSet({ hidden: e.target.checked })}
        />
      </td>
      <td className="num">
        <input
          type="checkbox"
          checked={pinned}
          onChange={(e) => onSet({ pinned: e.target.checked })}
        />
      </td>
      <td className="num">
        <input
          type="checkbox"
          checked={excluded}
          title="Exclude from net worth (treat as dust)"
          onChange={(e) => onSet({ exclude_from_networth: e.target.checked })}
        />
      </td>
    </tr>
  );
}
