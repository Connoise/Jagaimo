import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

/** True when both Supabase env vars are present. Used to show a setup banner. */
export const supabaseConfigured = Boolean(url && anonKey);

if (!supabaseConfigured) {
  // Fail loud in dev — a misconfigured viewer otherwise silently shows nothing.
  console.error(
    "Missing VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY — copy .env.example to .env"
  );
}

// All app tables live in the `tracking` schema. The anon key is RLS-constrained
// (read all; write only the four user-config tables) — see core/db/schema.sql.
export const supabase = createClient(url ?? "", anonKey ?? "", {
  db: { schema: "tracking" },
  auth: { persistSession: false },
});

export type PriceStatus = "live" | "last_close" | "stale_unlisted" | "unpriced";

export interface NetWorthRow {
  snapshot_ts: string;
  total_usd: string | number;
  any_problem: boolean;
}
