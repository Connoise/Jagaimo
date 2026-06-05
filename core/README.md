# Jagaimo — Phase 0 data core

A **read-only** asset tracker. It snapshots holdings from Alpaca and two
Base/EVM wallets every 15 minutes, values everything in USD, maintains a
per-instrument price + OHLC history for held *and* watchlisted instruments, and
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
├── sources/             # read-only adapters (alpaca, evm) + Holding/Source types
├── pricing/             # coingecko (live USD) + ohlc (backfill/maintain candles)
├── alerts/              # telegram (log+urgent) + net-worth threshold alert
├── targets.py           # price-target far/near/hit evaluation
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
everything but only write the four user-config tables
(`watchlist`, `instrument_groups`, `group_members`, `price_targets`). The
ingester owns the tables and bypasses RLS for its writes.

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
- **Timestamps are UTC** everywhere; local conversion happens only in the viewer.

## Live verification checklist

The automated tests cover all logic offline (`/.venv/bin/pytest -q`). The
following require live credentials/network and should be checked once on the
host:

- **D2:** `wallet_01` balances match Basescan to the token.
- **D3:** USDC ≈ $1 (live), ETH/AERO plausible.
- **D4:** Alpaca output matches the dashboard (or empty cleanly with no creds).
- **D6:** a simulated near + hit fire the log/urgent channels once.
- **D7:** a stock and a token each have multi-month daily + recent hourly bars.

## Read-only guarantee (plan §10)

This core contains **zero** order/trade-write calls. Verify:

```bash
grep -rniE 'submit_order|place_order|create_order|send_transaction|sendRawTransaction|eth_sendTransaction' . --include='*.py'
# (no matches)
```
