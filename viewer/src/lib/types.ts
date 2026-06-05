// Row shapes for the tracking schema. PostgREST returns NUMERIC columns as
// strings, so numeric fields are typed `string | number` and coerced via num().

export type PriceStatus = "live" | "last_close" | "stale_unlisted" | "unpriced";
export type AssetClass =
  | "equity"
  | "etf"
  | "crypto_spot"
  | "crypto_lp"
  | "cash";

export interface Instrument {
  instrument_id: number;
  asset_class: AssetClass;
  symbol: string;
  chain: string | null;
  address: string | null;
  decimals: number | null;
  coingecko_id: string | null;
  is_stablecoin: boolean;
  display_name: string | null;
}

export interface Holding {
  id: number;
  snapshot_ts: string;
  source: string;
  instrument_id: number;
  quantity: string | number;
  raw_quantity: string | number | null;
  price_usd: string | number | null;
  value_usd: string | number | null;
  price_as_of: string | null;
  price_status: PriceStatus;
  metadata: Record<string, unknown>;
}

export interface NetWorth {
  snapshot_ts: string;
  total_usd: string | number;
  by_source: Record<string, string | number>;
  by_asset_class: Record<string, string | number>;
  any_problem: boolean;
}

export interface PricePoint {
  instrument_id: number;
  ts: string;
  price_usd: string | number | null;
  price_status: PriceStatus;
}

export interface OhlcBar {
  instrument_id: number;
  timeframe: "1h" | "1d";
  ts: string;
  open: string | number | null;
  high: string | number | null;
  low: string | number | null;
  close: string | number | null;
  volume: string | number | null;
}

export interface WatchlistEntry {
  instrument_id: number;
  added_at: string;
  note: string | null;
}

export interface InstrumentGroup {
  group_id: number;
  name: string;
  created_at: string;
}

export interface GroupMember {
  group_id: number;
  instrument_id: number;
  weight: string | number;
}

export type TargetDirection = "above" | "below";
export type TargetState = "far" | "near" | "hit";

export interface PriceTarget {
  target_id: number;
  instrument_id: number;
  label: string | null;
  target_usd: string | number;
  direction: TargetDirection;
  near_pct: string | number;
  active: boolean;
  last_state: TargetState;
  last_notified: string | null;
  created_at: string;
}

export interface InstrumentPref {
  instrument_id: number;
  hidden: boolean;
  alias: string | null;
  pinned: boolean;
  exclude_from_networth: boolean;
  updated_at: string;
}

export type RequestKind = "equity" | "token";
export type RequestStatus = "pending" | "resolved" | "error";

export interface WatchlistRequest {
  request_id: number;
  kind: RequestKind;
  symbol: string | null;
  chain: string | null;
  address: string | null;
  note: string | null;
  status: RequestStatus;
  detail: string | null;
  instrument_id: number | null;
  created_at: string;
  resolved_at: string | null;
}

/** Coerce a PostgREST numeric (string) or number to a JS number. */
export function num(v: string | number | null | undefined): number {
  if (v === null || v === undefined) return NaN;
  return typeof v === "number" ? v : Number(v);
}
