import { formatUSD } from "../lib/format";

interface Props {
  title: string;
  breakdown: Record<string, number>;
  total: number;
}

const COLORS = [
  "#3fb950",
  "#58a6ff",
  "#d29922",
  "#bc8cff",
  "#f778ba",
  "#39c5cf",
  "#ff7b72",
];

/** V1 — per-source / per-asset-class breakdown with share bars. */
export function BreakdownPanel({ title, breakdown, total }: Props) {
  const entries = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);
  return (
    <div className="card">
      <h3>{title}</h3>
      {entries.length === 0 && <p className="muted">No data yet.</p>}
      <ul className="breakdown">
        {entries.map(([key, value], i) => {
          const pct = total > 0 ? (value / total) * 100 : 0;
          return (
            <li key={key}>
              <div className="breakdown-row">
                <span className="breakdown-key">{key}</span>
                <span className="breakdown-val">
                  {formatUSD(value)} <span className="muted">({pct.toFixed(1)}%)</span>
                </span>
              </div>
              <div className="bar">
                <div
                  className="bar-fill"
                  style={{
                    width: `${pct}%`,
                    background: COLORS[i % COLORS.length],
                  }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
