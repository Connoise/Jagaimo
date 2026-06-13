# Jagaimo

A **read-only** personal asset tracker. Jagaimo snapshots everything you hold —
stocks and ETFs, on-chain tokens, brokerage and custodial-exchange balances —
values it all in USD on a schedule, keeps a price + candlestick history for held
*and* watchlisted instruments, maintains an append-only trade ledger, and fires
price-target and net-worth alerts to Telegram. An interactive React viewer turns
that database into multi-timeframe charts, candlesticks, point-in-time
analytics, overlays, baskets, and descriptive statistics.

> **It never trades.** There are zero order/trade-write calls to any broker or
> wallet. Price targets and net-worth thresholds are *monitoring only* — they
> notify; they never place an order. This is a grep-verifiable guarantee (see
> [Read-only guarantee](#read-only-guarantee)).

The name is Japanese for *potato* (じゃがいも) — humble, dependable, keeps in the
cellar.

---

## What it does

- **Snapshots holdings every 15 minutes** from multiple read-only sources and
  values each position in USD.
- **Tracks prices and OHLC candles** for every instrument you hold *or*
  watchlist, so instrument charts have real multi-year history from day one.
- **Records a net-worth time series** plus per-source and per-asset-class
  breakdowns (the portfolio history is forward-only — it starts empty and fills
  going forward; it is never back-fabricated).
- **Keeps an append-only trade ledger** of trades and cash events, de-duplicated
  server-side so re-imports never double-count.
- **Evaluates alerts server-side**: per-instrument price targets (near / hit,
  de-duped) and a net-worth threshold alert (default: a move of **>5% and >$25**
  since the last alert, with a 60-minute cooldown), delivered to two Telegram
  channels (a routine *log* channel and an *urgent* channel).
- **Serves a React viewer** over a private network for exploring all of the
  above.

### Sources

All sources are **read-only, optional, and isolated** — a missing credential
skips that feed, and one source erroring mid-run never aborts the others; the
snapshot still records every source that succeeded.

| Source | Reads | How |
|---|---|---|
| **Alpaca** | Equity/ETF positions + cash | `alpaca-py` account/positions + market clock/calendar (never orders) |
| **Base wallets** (×2) | ERC-20 + native ETH on Base | Alchemy token discovery (spam-filtered), or a public-RPC + allowlist fallback |
| **Vanguard** | Brokerage holdings + transactions | CSV exports you drop in a folder; equities re-priced live, mutual funds keep exported NAV |
| **Coinbase** | Custodial balances + fills | CDP API key with **View** permission only; priced by CoinGecko id |

Crypto is priced by **contract address** on Base (native ETH / listed coins by
id). **Stablecoins are priced live**, not pinned to $1 — hiding a depeg would
defeat the tracker. Price state is an enum (`live | last_close |
stale_unlisted | unpriced`): a closed-market equity at `last_close` is correct
and normal; only `stale_unlisted` / `unpriced` are flagged as problems and can
drive alerts.

---

## Architecture

Two layers share one self-hosted **Supabase (Postgres)** database and talk only
over a **private network (tailnet)** — there is no app-level auth; the tailnet
ACL is the access control.

```
┌──────────────────┐      writes (service role)      ┌──────────────────────┐
│  core/  (Python) │ ───────────────────────────────▶│  Supabase / Postgres │
│  scheduled       │                                  │  (tracking schema)   │
│  ingester +      │                                  └──────────┬───────────┘
│  alerter         │                                             │ reads everything,
└──────────────────┘                                             │ writes only config
        │ Telegram alerts                            RLS-scoped   │ (anon role)
        ▼                                            anon key     ▼
   log / urgent                                      ┌──────────────────────┐
   channels                                          │ viewer/ (React + Vite)│
                                                      │ charts & analytics    │
                                                      └──────────────────────┘
```

- **`core/`** — the Python data core. Frontend-agnostic. Runs from cron as one
  idempotent snapshot every 15 minutes: fetch holdings → resolve instruments →
  price the held ∪ watchlisted set → write the `net_worth` rollup → evaluate
  targets and the net-worth alert → maintain OHLC candles. Owns the database via
  a least-privilege **ingester** Postgres role.

- **`viewer/`** — the React (Vite + TypeScript) front-end. Reads and writes
  Postgres through Supabase's auto-generated REST API using an **anon** key that
  is **RLS-constrained**: it can read every `tracking` table but write only the
  user-config tables (watchlist, groups, price targets, instrument preferences,
  and new-instrument requests). Holdings, prices, net worth, candles, and the
  trade ledger are read-only in the browser.

### Two data paths

Every view draws from one of two paths, which differ in history horizon *by
design*:

- **Portfolio path** (`net_worth` + `holdings`) — **forward-only**; starts empty
  at first run because past holdings are unknowable. Short ranges are labeled
  honestly ("tracking since &lt;date&gt;") rather than fabricated.
- **Instrument path** (`prices` + `ohlc_bars`) — **backfilled from APIs**, so it
  has genuine multi-year history immediately.

---

## Viewer features

| View | What it shows |
|---|---|
| **Portfolio** | Net-worth line / candlesticks, timeframe switcher (hour→all), click-to-pin point-in-time holdings + deltas, by-source & by-asset-class breakdown, holdings table with `price_status` labeling |
| **Instruments** | Per-instrument line / candlesticks, multi-instrument normalized overlay, watchlist CRUD, add a new stock/token to tracking, curate tracked instruments (alias / hide / pin / exclude-from-net-worth) |
| **Groups** | Weighted baskets rendered as a single synthetic series (absolute or indexed) |
| **Analysis** | Rate of change, rolling volatility, max drawdown, returns histogram — **descriptive only, no predictions or advice** |
| **Ledger** | Read-only trade ledger (Vanguard CSV transactions + Coinbase fills) with source/side/symbol filters and buy/sell/fee totals |
| **Targets** | Price-target CRUD + live distance-to-target; evaluation and alerts run server-side in the core |

**Adding & curating instruments:** holdings are derived from your real balances
and stay read-only. To track something new, the viewer enqueues a row in
`watchlist_requests` (it can't write the `instruments` dimension under RLS); the
ingester resolves it into an instrument + watchlist entry on its next run, so
it's priced and charted from then on. Curation (rename / hide / pin /
exclude-from-net-worth) lives in a separate `instrument_prefs` overlay the
browser may write.

---

## Tech stack

- **Core:** Python 3 · `psycopg` 3 · `requests` · `alpaca-py` · `web3` ·
  `coinbase-advanced-py` · `pytest`. Pricing via CoinGecko / GeckoTerminal;
  EVM discovery via Alchemy.
- **Store:** self-hosted Supabase (Postgres) — single `tracking` schema, with a
  `trading` schema reserved (unused) for future phases.
- **Viewer:** Vite + React + TypeScript · `@supabase/supabase-js` ·
  `@tanstack/react-query` · `lightweight-charts` (TradingView) for time-series &
  candlesticks · `recharts` for analysis charts.
- **Host:** a Linux host (no GPU). Production viewer is a static bundle served by
  Caddy as a systemd service bound to the private interface.

---

## Quick start

The two layers are set up independently. See each layer's README for the full
walkthrough — [`core/README.md`](core/README.md) and
[`viewer/README.md`](viewer/README.md).

**1. Database (one time):** create the least-privilege roles, then apply the
schema (idempotent, installs RLS) and seed.

```bash
cd core
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env          # fill in secrets
psql "$ADMIN_DATABASE_URL" -f db/roles.sql      # creates ingester + anon roles
.venv/bin/python -m db.client --apply-schema --seed
```

**2. Core — run a snapshot, then schedule it:**

```bash
.venv/bin/python ingest.py                      # one idempotent snapshot
# cron (every 15 min): see core/crontab.example
*/15 * * * * cd /path/to/jagaimo/core && .venv/bin/python ingest.py >> ingest.log 2>&1
```

**3. Viewer — point it at Supabase and run:**

```bash
cd viewer
npm install
cp .env.example .env        # set VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
npm run dev                 # http://<tailnet-host>:5173
```

For production, `npm run build` and serve `dist/` with Caddy as a systemd
service bound to the tailnet (`viewer/deploy/`).

---

## Repository layout

```
.
├── PHASE_0_TRACKER_PLAN.md   # full spec, locked decisions, and build milestones
├── core/                     # Python data core (ingester + alerter)
│   ├── config.py             # env + locked constants (ETH sentinel, thresholds, seeds)
│   ├── db/                   # roles.sql, schema.sql (tracking schema + RLS), client.py
│   ├── sources/              # read-only adapters: alpaca, evm, vanguard_csv, coinbase
│   ├── pricing/              # coingecko (live USD) + ohlc (backfill/maintain candles)
│   ├── alerts/               # telegram (log+urgent) + net-worth threshold
│   ├── targets.py            # price-target far/near/hit evaluation
│   ├── ledger.py             # append-only trade-ledger sync
│   ├── ingest.py             # orchestrator + cron entrypoint
│   └── tests/                # offline + DB-gated tests
└── viewer/                   # React (Vite + TS) front-end
    ├── src/
    │   ├── hooks/            # react-query data hooks
    │   ├── components/       # the six feature views + charts
    │   └── lib/             # pure analysis / timeframe / formatting utils
    └── deploy/              # Caddyfile + systemd unit
```

---

## Read-only guarantee

The core contains **zero** order/trade-write calls. Verify it yourself:

```bash
grep -rniE 'submit_order|place_order|create_order|preview_order|send_transaction|sendRawTransaction|eth_sendTransaction' core --include='*.py'
# (no matches)
```

Vanguard data is a CSV you export yourself; the Coinbase key needs only the
**View** permission. The browser's anon key is RLS-confined to reading data and
writing only user-config tables, so it can never corrupt ingester-owned data.

---

## Status & scope

This is **Phase 0** of a larger personal system, intentionally scoped to
*tracking only*. Explicitly **not** in scope here: order/trade execution,
strategy or signal generation, any trading agent's decision loop, cost-basis /
PnL accounting, and a kill switch. The schema namespacing (`tracking` now, a
reserved `trading` schema later) and the isolated source-adapter pattern are
designed so those can be added in future phases without reworking what exists.

For the complete specification, the locked build decisions, the data model DDL,
and the build milestones, see [`PHASE_0_TRACKER_PLAN.md`](PHASE_0_TRACKER_PLAN.md).
