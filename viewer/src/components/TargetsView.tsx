import { useState } from "react";
import {
  useTargets,
  distanceToTargetPct,
  type NewTarget,
} from "../hooks/useTargets";
import { useLatestPrices } from "../hooks/usePrices";
import { useInstrumentMap } from "../hooks/useInstruments";
import { num, type PriceTarget, type TargetDirection } from "../lib/types";
import { formatPct, formatPrice } from "../lib/format";
import { InstrumentPicker } from "./InstrumentPicker";

const STATE_PILL: Record<string, string> = {
  far: "pill",
  near: "pill pill-info",
  hit: "pill pill-warn",
};

interface FormState {
  instrument_id: number | null;
  target_usd: string;
  direction: TargetDirection;
  near_pct: string;
  label: string;
}

const EMPTY: FormState = {
  instrument_id: null,
  target_usd: "",
  direction: "above",
  near_pct: "2",
  label: "",
};

/** F8 — price-target CRUD (create + edit) + live distance-to-target. */
export function TargetsView() {
  const { data: targets, create, update, setActive, remove } = useTargets();
  const { data: latest } = useLatestPrices();
  const { data: instruments, map } = useInstrumentMap();

  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);

  const canSubmit = form.instrument_id != null && Number(form.target_usd) > 0;

  const beginEdit = (t: PriceTarget) => {
    setEditingId(t.target_id);
    setForm({
      instrument_id: t.instrument_id,
      target_usd: String(num(t.target_usd)),
      direction: t.direction,
      near_pct: String(num(t.near_pct)),
      label: t.label ?? "",
    });
  };

  const reset = () => {
    setEditingId(null);
    setForm(EMPTY);
  };

  const submit = () => {
    if (!canSubmit) return;
    const payload: NewTarget = {
      instrument_id: form.instrument_id!,
      target_usd: Number(form.target_usd),
      direction: form.direction,
      near_pct: Number(form.near_pct) || 2,
      label: form.label.trim() || undefined,
    };
    if (editingId != null) {
      update.mutate({ target_id: editingId, ...payload }, { onSuccess: reset });
    } else {
      create.mutate(payload, {
        onSuccess: () => setForm((f) => ({ ...f, target_usd: "", label: "" })),
      });
    }
  };

  const mutError = create.error || update.error;

  return (
    <div className="stack">
      <div className="card">
        <h2 className="m0">Price targets</h2>
        <p className="muted">
          Alerts only — targets notify (Telegram), they never trade. Evaluation
          runs in the core every snapshot.
        </p>
        <div className="row wrap">
          <InstrumentPicker
            instruments={instruments ?? []}
            value={form.instrument_id}
            onChange={(id) => setForm((f) => ({ ...f, instrument_id: id }))}
          />
          <select
            className="select"
            value={form.direction}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                direction: e.target.value as TargetDirection,
              }))
            }
          >
            <option value="above">above</option>
            <option value="below">below</option>
          </select>
          <input
            className="input input-sm"
            type="number"
            step="0.0001"
            placeholder="Target $"
            value={form.target_usd}
            onChange={(e) =>
              setForm((f) => ({ ...f, target_usd: e.target.value }))
            }
          />
          <input
            className="input input-sm"
            type="number"
            step="0.1"
            placeholder="Near %"
            value={form.near_pct}
            onChange={(e) => setForm((f) => ({ ...f, near_pct: e.target.value }))}
            title="Near band %"
          />
          <input
            className="input"
            placeholder="Label (optional)"
            value={form.label}
            onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))}
          />
          <button className="btn" disabled={!canSubmit} onClick={submit}>
            {editingId != null ? "Save changes" : "Add target"}
          </button>
          {editingId != null && (
            <button className="btn-sm" onClick={reset}>
              cancel
            </button>
          )}
        </div>
        {mutError && <p className="error">Failed: {String(mutError)}</p>}
      </div>

      <div className="card">
        <h3>Active &amp; inactive targets</h3>
        {targets && targets.length === 0 && (
          <p className="muted">No targets yet.</p>
        )}
        <table className="table">
          <thead>
            <tr>
              <th>Instrument</th>
              <th>Direction</th>
              <th className="num">Target</th>
              <th className="num">Current</th>
              <th className="num">Distance</th>
              <th>State</th>
              <th>Label</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(targets ?? []).map((t) => {
              const price = latest?.[t.instrument_id];
              const target = num(t.target_usd);
              const dist =
                price != null ? distanceToTargetPct(price, target) : NaN;
              return (
                <tr
                  key={t.target_id}
                  className={
                    (t.active ? "" : "row-muted") +
                    (editingId === t.target_id ? " row-editing" : "")
                  }
                >
                  <td>
                    <strong>{map.get(t.instrument_id)?.symbol ?? t.instrument_id}</strong>
                  </td>
                  <td>{t.direction}</td>
                  <td className="num">{formatPrice(target)}</td>
                  <td className="num">
                    {price != null ? formatPrice(price) : "—"}
                  </td>
                  <td className="num">{formatPct(dist)}</td>
                  <td>
                    <span className={STATE_PILL[t.last_state] ?? "pill"}>
                      {t.last_state}
                    </span>
                  </td>
                  <td className="muted">{t.label ?? "—"}</td>
                  <td className="num nowrap">
                    <button className="btn-sm" onClick={() => beginEdit(t)}>
                      edit
                    </button>{" "}
                    <button
                      className="btn-sm"
                      onClick={() =>
                        setActive.mutate({
                          target_id: t.target_id,
                          active: !t.active,
                        })
                      }
                    >
                      {t.active ? "pause" : "resume"}
                    </button>{" "}
                    <button
                      className="btn-sm"
                      onClick={() => remove.mutate(t.target_id)}
                    >
                      delete
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
