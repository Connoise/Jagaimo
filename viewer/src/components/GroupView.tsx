import { useMemo, useState } from "react";
import { useGroups, type GroupWithMembers } from "../hooks/useGroups";
import { useInstrumentMap } from "../hooks/useInstruments";
import { usePrices } from "../hooks/usePrices";
import { num } from "../lib/types";
import { normalizeToIndex, type ValuePoint } from "../lib/analysis";
import type { Timeframe } from "../lib/timeframe";
import { InstrumentPicker } from "./InstrumentPicker";
import { TimeframeSwitcher } from "./TimeframeSwitcher";
import { SeriesChart } from "./SeriesChart";

/** Weighted-sum basket series across the aligned snapshot timestamps. */
function basketSeries(
  prices: Record<number, ValuePoint[]>,
  weights: Map<number, number>
): ValuePoint[] {
  const acc = new Map<string, number>();
  for (const [idStr, points] of Object.entries(prices)) {
    const w = weights.get(Number(idStr)) ?? 1;
    for (const p of points) {
      acc.set(p.ts, (acc.get(p.ts) ?? 0) + w * p.value);
    }
  }
  return [...acc.entries()]
    .sort((a, b) => new Date(a[0]).getTime() - new Date(b[0]).getTime())
    .map(([ts, value]) => ({ ts, value }));
}

export function GroupView() {
  const { data: groups, createGroup, deleteGroup, addMember, removeMember } =
    useGroups();
  const { data: instruments, map } = useInstrumentMap();
  const [activeId, setActiveId] = useState<number | null>(null);
  const [tf, setTf] = useState<Timeframe>("month");
  const [scale, setScale] = useState<"absolute" | "index">("index");
  const [newName, setNewName] = useState("");
  const [pick, setPick] = useState<number | null>(null);
  const [weight, setWeight] = useState("1");

  const active: GroupWithMembers | undefined = useMemo(
    () => groups?.find((g) => g.group_id === activeId) ?? groups?.[0],
    [groups, activeId]
  );

  const memberIds = (active?.members ?? []).map((m) => m.instrument_id);
  const weights = new Map(
    (active?.members ?? []).map((m) => [m.instrument_id, num(m.weight)])
  );
  const pricesQ = usePrices(memberIds, tf);

  const series = useMemo(() => {
    if (!pricesQ.data) return [];
    const basket = basketSeries(pricesQ.data, weights);
    return scale === "index" ? normalizeToIndex(basket, 100) : basket;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pricesQ.data, scale, active?.members]);

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <h2 className="m0">Groups</h2>
          <div className="controls">
            <div className="segmented">
              <button
                className={scale === "index" ? "seg active" : "seg"}
                onClick={() => setScale("index")}
              >
                Index 100
              </button>
              <button
                className={scale === "absolute" ? "seg active" : "seg"}
                onClick={() => setScale("absolute")}
              >
                Weighted $
              </button>
            </div>
            <TimeframeSwitcher value={tf} onChange={setTf} />
          </div>
        </div>

        <div className="row">
          <select
            className="select"
            value={active?.group_id ?? ""}
            onChange={(e) => setActiveId(Number(e.target.value))}
          >
            <option value="" disabled>
              Select group…
            </option>
            {(groups ?? []).map((g) => (
              <option key={g.group_id} value={g.group_id}>
                {g.name}
              </option>
            ))}
          </select>
          <input
            className="input"
            placeholder="New group name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button
            className="btn"
            disabled={!newName.trim()}
            onClick={() => {
              createGroup.mutate(newName.trim());
              setNewName("");
            }}
          >
            Create
          </button>
          {active && (
            <button
              className="btn btn-danger"
              onClick={() => deleteGroup.mutate(active.group_id)}
            >
              Delete “{active.name}”
            </button>
          )}
        </div>

        {active ? (
          <>
            {series.length === 0 ? (
              <p className="muted">
                Add members with prices to render the basket series.
              </p>
            ) : (
              <SeriesChart
                lines={[{ id: "group", color: "#bc8cff", data: series }]}
              />
            )}
          </>
        ) : (
          <p className="muted">Create a group to begin.</p>
        )}
      </div>

      {active && (
        <div className="card">
          <h3>Members of “{active.name}”</h3>
          <div className="row">
            <InstrumentPicker
              instruments={(instruments ?? []).filter(
                (i) => !memberIds.includes(i.instrument_id)
              )}
              value={pick}
              onChange={setPick}
              placeholder="Add member…"
            />
            <input
              className="input input-sm"
              type="number"
              step="0.1"
              value={weight}
              onChange={(e) => setWeight(e.target.value)}
              title="Weight"
            />
            <button
              className="btn"
              disabled={pick == null}
              onClick={() => {
                if (pick != null) {
                  addMember.mutate({
                    group_id: active.group_id,
                    instrument_id: pick,
                    weight: Number(weight) || 1,
                  });
                  setPick(null);
                }
              }}
            >
              Add
            </button>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Instrument</th>
                <th className="num">Weight</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {active.members.map((m) => (
                <tr key={m.instrument_id}>
                  <td>
                    <strong>{map.get(m.instrument_id)?.symbol ?? m.instrument_id}</strong>
                  </td>
                  <td className="num">{num(m.weight)}</td>
                  <td className="num">
                    <button
                      className="btn-sm"
                      onClick={() =>
                        removeMember.mutate({
                          group_id: active.group_id,
                          instrument_id: m.instrument_id,
                        })
                      }
                    >
                      remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
