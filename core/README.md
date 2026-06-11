# Jagaimo — Phase 0 data core

A **read-only** asset tracker. It snapshots holdings from Alpaca, two Base/EVM
wallets, Vanguard (CSV exports), and Coinbase (read-only API) every 15 minutes,
values everything in USD, maintains a per-instrument price + OHLC history for
held *and* watchlisted instruments, keeps an append-only trade ledger, and
evaluates price-target and net-worth alerts. **No trading, no order placement.**

The React viewer lives in `../viewer` and reads/writes the same Supabase
Postgres over the tailnet. This directory is the Python core only.

See `../PHASE_0_TRACKER_PLAN.md` for the full spec and locked decisions.

## Layout

```
core/
├── config.py            # env + locked constants (sentinel, thresholds, seeds)
├── db/
│   ├── roles.sql        # one-time: create least-privilege ingester + anon roles
│   ├── schema.sql       # tracking schema: tables, views, RLS policies
│   └── client.py        # psycopg writers/readers + get_or_create_instrument
├── sources/             # read-only adapters (alpaca, evm, vanguard_csv,
│                        #   coinbase) + Holding/Source types
├── pricing/             # coingecko (live USD) + ohlc (backfill/maintain candles)
├── alerts/              # telegram (log+urgent) + net-worth threshold alert
├── targets.py           # price-target far/near/hit evaluation
├── ledger.py            # trade-ledger sync (vanguard CSV txns, coinbase fills)
├── ingest.py            # orchestrator + cron entrypoint
├── obs.py               # logging setup (text or JAGAIMO_LOG_JSON=true)
└── tests/               # offline + DB-gated tests
```

## Setup

```bash
cd core
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env      # then fill in secrets
```

### Database (one time)

As a Postgres superuser, create the roles, then apply the schema as the
ingester:

```bash
psql "$ADMIN_DATABASE_URL" -f db/roles.sql      # creates ingester + anon
.venv/bin/python -m db.client --apply-schema --seed
```

`schema.sql` is idempotent and installs RLS so the browser `anon` role can read
everything but only write the user-config tables (`watchlist`,
`instrument_groups`, `group_members`, `price_targets`, `watchlist_requests`,
`instrument_prefs`). The ingester owns the tables and bypasses RLS for its
writes; data tables — including the `transactions` ledger — are read-only to
the browser.

## Run

```bash
.venv/bin/python ingest.py        # one idempotent snapshot
```

Schedule every 15 minutes via cron (see `crontab.example`):

```cron
*/15 * * * * cd /path/to/asset-tracker/core && .venv/bin/python ingest.py >> ingest.log 2>&1
```

Set `JAGAIMO_LOG_JSON=true` for one-line JSON logs.

## Configuration notes

- **Sources are optional and isolated.** Missing Alpaca creds → equities
  skipped. A source that errors mid-run is logged and skipped; the snapshot
  still records every other source.
- **EVM discovery:** Alchemy (`getTokenBalances` + `getTokenMetadata`, spam
  filtered) is the primary path. Without an Alchemy key, set `BASE_RPC_URL` and
  `TOKEN_ALLOWLIST` (comma-separated contract addresses) for the public-RPC
  fallback; only native ETH is discoverable without an allowlist.
- **Pricing:** crypto by contract on Base (native ETH / listed coins by id);
  stablecoins priced **live** so a depeg is visible. `price_status` is an enum
  (`live | last_close | stale_unlisted | unpriced`); only the last two are
  "problems" that set `any_problem` and drive alerts.
- **Vanguard (file-based, no API/aggregator):** set `VANGUARD_CSV_DIR` to a
  directory (or single file) and drop CSV exports there (vanguard.com → My
  Accounts → Transaction history → Download → CSV). The newest export's
  *holdings* section becomes the position snapshot each run; *transaction*
  sections feed the trade ledger. Equity/ETF rows are re-priced live via
  Alpaca market data every run; mutual funds keep the exported NAV
  (`last_close`) and flip to `stale_unlisted` once the file exceeds
  `VANGUARD_CSV_STALE_DAYS` — your nudge to re-export. Non-ticker holdings
  (CDs, bonds) are skipped with a warning. Validate or import a file by hand:
  `python -m sources.vanguard_csv export.csv [--dry-run]`.
- **Coinbase (read-only API):** create a CDP API key with the **View**
  permission only and set `COINBASE_KEY_FILE` (path to the downloaded key
  json) or `COINBASE_API_KEY_NAME` + `COINBASE_API_PRIVATE_KEY`. Custodial
  balances have no contract address, so assets are priced by CoinGecko id via
  a built-in symbol map; unmapped symbols show `stale_unlisted` until added to
  `COINBASE_COINGECKO_IDS` ("SYM:id,SYM:id").
- **Trade ledger:** `tracking.transactions` is an append-only record of trades
  and cash events — Vanguard CSV transaction sections plus Coinbase Advanced
  Trade fills (fetched incrementally; conversions/staking/transfers are not
  fills and aren't recorded). Dedup is by deterministic natural key, so
  re-importing overlapping exports never double-counts (two genuinely
  identical same-day rows in one export both import, via an occurrence
  index). `amount_usd` is signed net cash flow: negative = cash out. This is
  a record, **not** a cost-basis/PnL engine (deferred, plan §11). Note:
  Vanguard exports only ~18 months of transactions to CSV — older history is
  unknowable here.
- **Timestamps are UTC** everywhere; local conversion happens only in the viewer.
- **Adding instruments:** the viewer enqueues new stocks/tokens in
  `tracking.watchlist_requests` (it can't write `instruments` under RLS). Each
  run, `watchlist_requests.process_watchlist_requests` validates the input,
  `get_or_create`s the instrument, adds it to the watchlist, and marks the
  request `resolved`/`error` — so a new instrument is priced and backfilled the
  same run it's added.

## Live verification checklist

The automated tests cover all logic offline (`/.venv/bin/pytest -q`). The
following require live credentials/network and should be checked once on the
host:

- **D2:** `wallet_01` balances match Basescan to the token.
- **D3:** USDC ≈ $1 (live), ETH/AERO plausible.
- **D4:** Alpaca output matches the dashboard (or empty cleanly with no creds).
- **D6:** a simulated near + hit fire the log/urgent channels once.
- **D7:** a stock and a token each have multi-month daily + recent hourly bars.
- **Vanguard:** an export dropped in `VANGUARD_CSV_DIR` shows positions next
  run; re-running on the same file adds 0 ledger rows.
- **Coinbase:** balances match the app; fills appear once and only once.

## Read-only guarantee (plan §10)

This core contains **zero** order/trade-write calls. Verify:

```bash
grep -rniE 'submit_order|place_order|create_order|preview_order|send_transaction|sendRawTransaction|eth_sendTransaction' . --include='*.py'
# (no matches)
```

Vanguard is a file you export yourself; the Coinbase key needs only the View
permission (create it read-only) — only `get_accounts`/`get_fills` are called.
