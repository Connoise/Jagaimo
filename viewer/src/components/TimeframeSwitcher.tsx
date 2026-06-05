import {
  TIMEFRAMES,
  TIMEFRAME_LABEL,
  type Timeframe,
} from "../lib/timeframe";

interface Props {
  value: Timeframe;
  onChange: (tf: Timeframe) => void;
}

/** F1 — segmented control selecting the active timeframe. */
export function TimeframeSwitcher({ value, onChange }: Props) {
  return (
    <div className="segmented" role="tablist" aria-label="Timeframe">
      {TIMEFRAMES.map((tf) => (
        <button
          key={tf}
          role="tab"
          aria-selected={value === tf}
          className={value === tf ? "seg active" : "seg"}
          onClick={() => onChange(tf)}
        >
          {TIMEFRAME_LABEL[tf]}
        </button>
      ))}
    </div>
  );
}
