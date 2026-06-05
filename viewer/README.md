# Jagaimo — Viewer (React)

Interactive front-end for the Phase 0 tracker. Reads/writes the self-hosted
Supabase Postgres (the `tracking` schema) over the tailnet via PostgREST. No
app-level auth — access control is the tailnet ACL (decision §2.11). The anon
key is RLS-constrained (reads all, writes only the four user-config tables).

**Status: V0** — Vite + React + TS scaffold with a live net-worth line chart
(`@tanstack/react-query` + `lightweight-charts`). Features F1–F8 (V1–V9) build
on this foundation.

## Setup

```bash
cd viewer
npm install
cp .env.example .env     # set VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
npm run dev              # http://<tailnet-host>:5173
```

`npm run build` produces a static bundle in `dist/` (served by Caddy/nginx as a
systemd service in V9). `npm run typecheck` runs `tsc` with no emit.

## Structure

```
src/
├── main.tsx                  # react-query provider + mount
├── App.tsx                   # shell
├── lib/supabase.ts           # supabase-js client scoped to the tracking schema
├── hooks/useNetWorth.ts      # net_worth rollup query
└── components/NetWorthChart.tsx
```

## V0 done-when

Chart shows live net worth from the DB over the tailnet. Requires the core to
have written at least one `net_worth` snapshot and Supabase/PostgREST to be
reachable at `VITE_SUPABASE_URL`.
