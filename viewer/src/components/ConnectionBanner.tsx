import { supabaseConfigured } from "../lib/supabase";

/** Visible setup warning when Supabase env vars are missing. */
export function ConnectionBanner() {
  if (supabaseConfigured) return null;
  return (
    <div className="banner">
      ⚠ Supabase is not configured. Copy <code>.env.example</code> to{" "}
      <code>.env</code> and set <code>VITE_SUPABASE_URL</code> and{" "}
      <code>VITE_SUPABASE_ANON_KEY</code>, then restart the dev server.
    </div>
  );
}
