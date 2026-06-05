import { useMemo, useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { useNetWorth } from "../hooks/useNetWorth";
import { useInstrumentMap } from "../hooks/useInstruments";
import { usePrices } from "../hooks/usePrices";
import { filterByWindow, type Timeframe } from "../lib/timeframe";
import {
  maxDrawdown,
  rateOfChange,
  returnsHistogram,
  rollingRateOfChange,
  rollingVolatility,
  simpleReturns,
  stdev,
  type ValuePoint,
} from "../lib/analysis";
import { formatDate, formatPct } from "../lib/format";
import { InstrumentPicker } from "./InstrumentPicker";
import { TimeframeSwitcher } from "./TimeframeSwitcher";

type Source = "portfolio" | "instrument";

export function AnalysisView() {
  const [source, setSource] = useState<Source>("portfolio");
  const [tf, setTf] = useState<Timeframe>("month");
  const [instrumentId, setInstrumentId] = useState<number | null>(null);

  const { data: nw } = useNetWorth();
  const { data: instruments } = useInstrumentMap();
  const pricesQ = usePrices(
    source === "instrument" && instrumentId != null ? [instrumentId] : [],
    tf
  );

  const points: ValuePoint[] = useMemo(() => {
    if (source === "portfolio") {
      return (nw ? filterByWindow(nw, tf) : []).map((p) => ({
        ts: p.ts,
        value: p.total,
      }));
    }
    return instrumentId != null ? pricesQ.data?.[instrumentId] ?? [] : [];
  }, [source, nw, tf, pricesQ.data, instrumentId]);

  const values = points.map((p) => p.value);
  const rets = simpleReturns(values);
  const window = Math.max(3, Math.min(24, Math.floor(points.length / 6)));

  const roc = rateOfChange(values);
  const vol = stdev(rets) * 100;
  const dd = maxDrawdown(points);
  const rollRoc = rollingRateOfChange(points, window);
  const rollVol = rollingVolatility(points, window);
  const hist = returnsHistogram(rets, 21);

  const enoughData = points.length >= 5;

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <h2 className="m0">Analysis</h2>
          <div className="controls">
            <div className="segmented">
              <button
                className={source === "portfolio" ? "seg active" : "seg"}
                onClick={() => setSource("portfolio")}
              >
                Portfolio
              </button>
              <button
                className={source === "instrument" ? "seg active" : "seg"}
                onClick={() => setSource("instrument")}
              >
                Instrument
              </button>
            </div>
            <TimeframeSwitcher value={tf} onChange={setTf} />
          </div>
        </div>

        {source === "instrument" && (
          <div className="row">
            <InstrumentPicker
              instruments={instruments ?? []}
              value={instrumentId}
              onChange={setInstrumentId}
            />
          </div>
        )}

        <p className="muted">
          Descriptive statistics over the selected window — past behavior only,
          not predictions or advice.
        </p>

        {!enoughData ? (
          <p className="muted">Not enough data in this window yet.</p>
        ) : (
          <>
            <div className="stat-row">
              <Stat label="Rate of change" value={formatPct(roc)} positive={roc >= 0} />
              <Stat label="Volatility (σ of returns)" value={formatPct(vol)} />
              <Stat
                label="Max drawdown"
                value={formatPct(dd.maxDrawdownPct)}
                positive={false}
              />
              <Stat label="Observations" value={String(points.length)} />
            </div>

            <div className="grid-2">
              <MiniChart title={`Rolling rate of change (${window}-period)`}>
                <LineChart data={toRecharts(rollRoc)}>
                  <CartesianGrid stroke="#1c2128" />
                  <XAxis dataKey="label" hide />
                  <YAxis width={48} tick={{ fill: "#8b949e", fontSize: 11 }} />
                  <Tooltip contentStyle={TOOLTIP} />
                  <Line dataKey="value" stroke="#58a6ff" dot={false} />
                </LineChart>
              </MiniChart>

              <MiniChart title={`Rolling volatility (${window}-period σ)`}>
                <LineChart data={toRecharts(rollVol)}>
                  <CartesianGrid stroke="#1c2128" />
                  <XAxis dataKey="label" hide />
                  <YAxis width={48} tick={{ fill: "#8b949e", fontSize: 11 }} />
                  <Tooltip contentStyle={TOOLTIP} />
                  <Line dataKey="value" stroke="#d29922" dot={false} />
                </LineChart>
              </MiniChart>

              <MiniChart title="Drawdown (underwater)">
                <AreaChart data={toRecharts(dd.series)}>
                  <CartesianGrid stroke="#1c2128" />
                  <XAxis dataKey="label" hide />
                  <YAxis width={48} tick={{ fill: "#8b949e", fontSize: 11 }} />
                  <Tooltip contentStyle={TOOLTIP} />
                  <Area dataKey="value" stroke="#f85149" fill="#f8514933" />
                </AreaChart>
              </MiniChart>

              <MiniChart title="Returns histogram">
                <BarChart data={hist}>
                  <CartesianGrid stroke="#1c2128" />
                  <XAxis dataKey="label" tick={{ fill: "#8b949e", fontSize: 10 }} />
                  <YAxis width={36} tick={{ fill: "#8b949e", fontSize: 11 }} />
                  <Tooltip contentStyle={TOOLTIP} />
                  <Bar dataKey="count" fill="#3fb950" />
                </BarChart>
              </MiniChart>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const TOOLTIP = {
  background: "#161b22",
  border: "1px solid #30363d",
  color: "#c9d1d9",
};

function toRecharts(points: ValuePoint[]) {
  return points.map((p) => ({ label: formatDate(p.ts), value: p.value }));
}

function MiniChart({ title, children }: { title: string; children: React.ReactElement }) {
  return (
    <div className="card card-inset">
      <h4>{title}</h4>
      <ResponsiveContainer width="100%" height={200}>
        {children}
      </ResponsiveContainer>
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
