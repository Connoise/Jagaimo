import type { Instrument } from "../lib/types";

interface Props {
  instruments: Instrument[];
  value: number | null;
  onChange: (id: number) => void;
  placeholder?: string;
}

export function InstrumentPicker({
  instruments,
  value,
  onChange,
  placeholder = "Select instrument…",
}: Props) {
  return (
    <select
      className="select"
      value={value ?? ""}
      onChange={(e) => onChange(Number(e.target.value))}
    >
      <option value="" disabled>
        {placeholder}
      </option>
      {instruments.map((i) => (
        <option key={i.instrument_id} value={i.instrument_id}>
          {i.symbol}
          {i.display_name ? ` · ${i.display_name}` : ""}
        </option>
      ))}
    </select>
  );
}
