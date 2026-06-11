# Jagaimo — Viewer (React)

Interactive front-end for the Phase 0 tracker. Reads/writes the self-hosted
Supabase Postgres (the `tracking` schema) over the tailnet via PostgREST. No
app-level auth — access control is the tailnet ACL (decision §2.11). The anon
key is RLS-constrained: it reads everything but writes only the user-config
tables (`watchlist`, `instrument_groups`, `group_members`, `price_targets`,
`watchlist_requests`, `instrument_prefs`); data tables — including the
`transactions` ledger — are read-only in the browser.

## Features (F1–F8 / V1–V9)

| View | Features |
|------|----------|
| **Portfolio** | Net-worth line/candlesticks, timeframe switcher (F1), click-to-pin point-in-time (F2/F3), by-source & by-asset-class breakdown, holdings table with `price_status` labeling (V1/V2/V3/V4) |
| **Instruments** | Per-instrument line/candlesticks from `prices`/`ohlc_bars`, multi-instrument normalized overlay (F5), watchlist CRUD, **add a new stock/token** to tracking, **curate tracked instruments** (alias / hide / pin / exclude-from-net-worth) |
| **Groups** | Weighted baskets as a single series — absolute or indexed (F6) |
| **Analysis** | Rate of change, rolling volatility, max drawdown, returns histogram (F7) — descriptive only, no predictions |
| **Ledger** | Read-only trade ledger: trades & cash events imported by the core (Vanguard CSV transaction sections, Coinbase fills) with source/side/symbol filters and buy/sell/fee totals. Append-only and de-duplicated server-side; holdings snapshots stay authoritative for "now" |
| **Targets** | Price-target CRUD + live distance-to-target (F8); evaluation/alerts run server-side in the core |

## Stack

Vite + React + TypeScript · `@supabase/supabase-js` (scoped to the `tracking`
schema) · `@tanstack/react-query` · `lightweight-charts` (time-series &
candlesticks) · `recharts` (analysis charts).

The top bar shows a last-updated indicator (with a staleness warning if the
ingester appears to have stopped) and a manual refresh. A setup banner appears
if the Supabase env vars are missing.

### Adding instruments

Holdings are read-only — derived from your real Alpaca/wallet balances. To
**track a new stock or token** the system hasn't seen, the Instruments tab
enqueues a row in `tracking.watchlist_requests` (the browser can't write
`instruments` directly under RLS). The ingester resolves each request into an
instrument + watchlist entry on its next run, so it's priced and charted from
then on — and shows up in holdings automatically if a connected source ever
holds it.

To **edit what's tracked**, the canonical `instruments` dimension stays
ingester-owned (it's the join hub for all holdings/prices/history). Curation
lives in a separate `instrument_prefs` overlay the browser may write: rename
(alias), hide spam/dust from views, pin favorites, or mark dust as
excluded-from-net-worth (the ingester drops it from the rollup total on the next
run, but still records the holding). Identity/metadata corrections
(`coingecko_id`, `decimals`) remain a server-side concern, not a browser form.

## Setup

```bash
cd viewer
npm install
cp .env.example .env     # set VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
npm run dev              # http://<tailnet-host>:5173
```

- `npm run build` → static bundle in `dist/`
- `npm run typecheck` → `tsc` no-emit
- `npm run test` → vitest (pure analytics/timeframe units)

## Layout

```
src/
├── main.tsx / App.tsx            # provider + tabbed shell
├── lib/                          # types, format, timeframe, analysis (pure)
├── hooks/                        # react-query: net worth, holdings, prices,
│                                 #   ohlc, instruments, watchlist, groups, targets
└── components/                   # SeriesChart + the five feature views
```

## V9 — Build & serve (production)

Serve the static `dist/` with Caddy as a systemd service bound to the tailnet
interface (`deploy/Caddyfile`, `deploy/jagaimo-viewer.service`):

```bash
npm run build
sudo mkdir -p /opt/jagaimo/viewer && sudo cp -r dist deploy /opt/jagaimo/viewer/
# edit /opt/jagaimo/viewer/deploy/Caddyfile -> set this host's tailscale IP
sudo cp deploy/jagaimo-viewer.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now jagaimo-viewer
```

The bundle is reachable only over the tailnet; RLS is enforced server-side;
there is no app auth. *(Optional)* enable Supabase realtime for live-updating
charts.

## V0 done-when (and beyond)

Charts render live from the DB over the tailnet once Supabase/PostgREST is
reachable at `VITE_SUPABASE_URL` and the core has written at least one snapshot.
Portfolio history is forward-only and labeled "tracking since <date>"; over-long
ranges show all available history rather than fabricating data.
