# Phase 0 — Unified Asset Tracker — Development Plan

> **Build scope:** a **read-only** tracker that pulls balances/positions from
> Alpaca and two Base/EVM wallets, values everything in USD, stores point-in-time
> snapshots, and shows a unified net-worth dashboard. **No trading, no order
> placement, no agent logic.** This document is the build spec for Claude Code.
>
> Everything about the larger trading system lives in §9 only, as
> forward-compatibility notes that shape the schema's *shape* but must **not**
> add features to this build.

**Target host:** Benten-do (Ubuntu, no GPU) · **Store:** existing self-hosted Supabase (Postgres) · **Language:** Python · **Access:** dashboard reachable over Tailscale

---

## 1. What this build is (and is not)

**Is:**
- A scheduled ingester that reads holdings from three sources and prices them in USD.
- A Postgres schema holding instrument definitions, holdings snapshots, and a net-worth rollup.
- A Streamlit dashboard: total net worth over time, per-source breakdown, current holdings, price-staleness flags.

**Is NOT (do not build in Phase 0):**
- Any order/trade execution or write calls to a broker or wallet.
- Backtrader, strategy rules, or signal generation.
- The crypto agent's decision loop or decision-log population.
- A kill switch / `trading_enabled` enforcement.
- Paper↔live promotion logic.

If a task seems to require any of the above, it is out of scope — stop and flag it.

---

## 2. Decisions already locked (do not re-open)

These came out of the design phase; treat them as given.

- **Snapshot cadence:** every 15 minutes. Equities simply won't change outside market hours — that is correct behavior, not a bug.
- **Valuation:** convert everything to USD at ingestion. Store **two timestamps** per holding — the snapshot time and the price's `as_of` time — plus a `price_stale` boolean. Equities marked at last trade/close; **no extended-hours quotes**.
- **Store:** a **single** Postgres instance (the existing Supabase). Use a dedicated `tracking` schema. (A future `trading` schema is reserved — see §9 — but is not created here.)
- **Scheduling:** plain **cron on Benten-do** with a single idempotent entrypoint. No scheduler service needed at this scale.
- **Instruments:** use an `instruments` dimension table (canonical id → ticker *or* `(chain, address)`); other tables reference `instrument_id`. Store crypto quantities as high-scale `NUMERIC`, and keep the raw integer + decimals so precision is never lost.
- **Alerting (optional only):** if built, route to **two Telegram targets** — a quiet log channel and an urgent one. This is a stretch item (§7, M9), not part of the tracker core.

---

## 3. Sources & valuation

Three sources, all **read-only**. Each wallet is just an address handed to the same EVM adapter.

| Source key | What it reads | How | Pricing |
|---|---|---|---|
| `alpaca` | equity/ETF positions + cash/equity | `alpaca-py` SDK, account + positions endpoints (read only — never orders) | last trade/close from Alpaca |
| `wallet_standard` | ERC-20 + native balances on Base | Alchemy free tier, or public Base RPC + `web3.py` | CoinGecko token price |
| `wallet_01` | ERC-20 + native balances on Base (agentic wallet `0x2b58b8F908eF3a443bB6eF2213FFc2917804D3b4`) | same EVM adapter as above | CoinGecko token price |

Notes:
- **Alpaca is optional at runtime.** If no account is funded / no positions exist, the equities source contributes nothing and the tracker runs fine on the wallets alone. Build it so a missing/empty source degrades gracefully rather than erroring.
- **LP positions are deferred.** Phase 0 values only fungible spot balances (USDC, WETH/ETH, AERO, etc.). If `wallet_01` ever holds an Aerodrome LP token, mark it `price_stale = true` / value `NULL` and label it "unvalued (LP — Phase 1)". Proper LP marking is explicitly future work.
- CoinGecko's free tier is sufficient for a handful of tokens; cache prices within a snapshot run to stay well under rate limits.

---

## 4. Data model (`tracking` schema)

Minimal and correct. Three tables; the dashboard derives everything from them.

```sql
CREATE SCHEMA IF NOT EXISTS tracking;

-- Dimension: one row per distinct instrument ever seen.
CREATE TABLE tracking.instruments (
    instrument_id   BIGSERIAL PRIMARY KEY,
    asset_class     TEXT NOT NULL,            -- 'equity' | 'etf' | 'crypto_spot' | 'crypto_lp'
    symbol          TEXT NOT NULL,            -- 'VOO', 'USDC', 'AERO', ...
    chain           TEXT,                     -- NULL for equities; 'base' etc. for crypto
    address         TEXT,                     -- NULL for equities; contract addr (or native sentinel) for crypto
    decimals        INT,                      -- token decimals; NULL/0 for equities
    coingecko_id    TEXT,                     -- pricing key for crypto; NULL for equities
    display_name    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset_class, symbol, chain, address)
);

-- Fact: every holding at every snapshot, valued in USD.
CREATE TABLE tracking.holdings (
    id              BIGSERIAL PRIMARY KEY,
    snapshot_ts     TIMESTAMPTZ NOT NULL,
    source          TEXT NOT NULL,            -- 'alpaca' | 'wallet_standard' | 'wallet_01'
    instrument_id   BIGINT NOT NULL REFERENCES tracking.instruments(instrument_id),
    quantity        NUMERIC(78, 30) NOT NULL, -- human-readable quantity (decimals applied)
    raw_quantity    NUMERIC(78, 0),           -- raw integer for crypto (precision-safe); NULL for equities
    price_usd       NUMERIC(38, 18),          -- NULL if unpriced
    value_usd       NUMERIC(38, 18),          -- quantity * price_usd; NULL if unpriced
    price_as_of     TIMESTAMPTZ,              -- when the price was true
    price_stale     BOOLEAN NOT NULL DEFAULT false,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX ON tracking.holdings (snapshot_ts);
CREATE INDEX ON tracking.holdings (source, snapshot_ts);

-- Rollup: cheap time series for the net-worth chart (derived from holdings each run).
CREATE TABLE tracking.net_worth (
    snapshot_ts     TIMESTAMPTZ PRIMARY KEY,
    total_usd       NUMERIC(38, 18) NOT NULL,
    by_source       JSONB NOT NULL,           -- {"alpaca": ..., "wallet_standard": ..., "wallet_01": ...}
    by_asset_class  JSONB NOT NULL,
    any_stale       BOOLEAN NOT NULL DEFAULT false
);
```

`get_or_create` the instrument on each ingest so new tokens/tickers self-register.

---

## 5. Project structure

```
tracker/
├── .env.example
├── README.md
├── requirements.txt
├── config.py              # load env; constants (interval, wallet addresses, source toggles)
├── db/
│   ├── schema.sql         # the DDL from §4
│   └── client.py          # psycopg connection + get_or_create_instrument + write helpers
├── sources/
│   ├── base.py            # Holding dataclass + Source protocol: fetch_holdings() -> list[Holding]
│   ├── alpaca_source.py   # read-only positions + cash (NO order calls)
│   └── evm_source.py      # token + native balances for a list of Base addresses
├── pricing/
│   └── coingecko.py       # token symbol/contract -> USD, with per-run cache
├── ingest.py              # ORCHESTRATOR + cron entrypoint
├── dashboard/
│   └── app.py             # Streamlit
└── tests/
    └── test_sources.py    # dry-run / smoke tests per adapter
```

**Env (`.env.example`):**
```
# Postgres (existing Supabase)
DATABASE_URL=postgresql://...

# Alpaca (read-only use; paper or live). Optional — omit to skip equities.
ALPACA_API_KEY_ID=
ALPACA_API_SECRET_KEY=
ALPACA_BASE_URL=https://api.alpaca.markets   # or paper-api for paper

# EVM / Base
ALCHEMY_API_KEY=            # or set BASE_RPC_URL for public RPC + web3.py
BASE_RPC_URL=
WALLET_STANDARD_ADDRESS=
WALLET_01_ADDRESS=0x2b58b8F908eF3a443bB6eF2213FFc2917804D3b4

# CoinGecko (free tier; demo key optional)
COINGECKO_API_KEY=

# Telegram (OPTIONAL — only for M9 stretch alerting)
TELEGRAM_BOT_TOKEN=
TELEGRAM_LOG_CHAT_ID=
TELEGRAM_ALERT_CHAT_ID=
```

---

## 6. Ingestion flow (`ingest.py`)

One idempotent run, safe to call every 15 min from cron:

1. Take a single `snapshot_ts = now()` for the whole run.
2. For each **enabled** source, call `fetch_holdings()` → list of `(symbol/address, raw_qty, decimals, asset_class, chain)`.
3. `get_or_create_instrument` for each; resolve `instrument_id`.
4. Price each holding (equities from Alpaca; crypto from CoinGecko, cached per run). Set `price_stale`/`NULL` where unpriced (LP, off-hours equities, lookup miss).
5. Insert `holdings` rows for this `snapshot_ts`.
6. Compute and insert the `net_worth` rollup row (total + by_source + by_asset_class + any_stale).
7. Log a one-line summary; exit non-zero on hard failure so cron surfaces it.

Resilience: a failure in one source must not abort the others — record what succeeded, mark the rest absent, and keep going.

**Cron (Benten-do):**
```
*/15 * * * * cd /home/connoise/.../tracker && .venv/bin/python ingest.py >> ingest.log 2>&1
```

---

## 7. Build milestones (sequenced for Claude Code)

Each milestone has a concrete "Done when." Build and verify in order.

- **M0 — Skeleton & config.** Repo structure, `requirements.txt`, `config.py`, `.env.example`. *Done when:* `python -c "import config"` loads env cleanly with sane errors for missing required vars.
- **M1 — DB.** `schema.sql` applied to the `tracking` schema; `db/client.py` connects and `get_or_create_instrument` works. *Done when:* tables exist and an instrument can be inserted/fetched idempotently.
- **M2 — EVM source.** `evm_source.py` returns native + ERC-20 balances for a list of Base addresses (both wallets). *Done when:* balances for `WALLET_01_ADDRESS` match a Base block explorer (e.g. Basescan) to the token.
- **M3 — Pricing.** `coingecko.py` maps tokens → USD with a per-run cache. *Done when:* USDC ≈ $1 and ETH/AERO return plausible live prices.
- **M4 — Alpaca source.** `alpaca_source.py` returns positions + cash read-only; absent/empty account degrades gracefully. *Done when:* output matches the Alpaca dashboard (or returns empty cleanly with no creds).
- **M5 — Orchestrator.** `ingest.py` ties it together and writes one full snapshot + rollup. *Done when:* a manual run populates `holdings` and `net_worth` for one `snapshot_ts`, totals foot, staleness flags correct.
- **M6 — Schedule.** Cron entry on Benten-do; idempotent across runs. *Done when:* it runs unattended every 15 min for an hour with no errors and a growing `net_worth` series.
- **M7 — Dashboard.** `dashboard/app.py` (Streamlit): net-worth time series, per-source and per-asset-class breakdown, current-holdings table, explicit "equities at last close / N values stale" labeling. *Done when:* it renders from the DB and is reachable over Tailscale.
- **M8 — Hardening.** Structured logging, per-source error isolation, README with setup/run steps. *Done when:* killing one source (bad key) still produces a partial snapshot and a clear log line.
- **M9 — (OPTIONAL) Alerting.** Telegram message to the **urgent** channel on net-worth change beyond a threshold; routine summaries to the **log** channel. *Done when:* a simulated large delta fires the urgent path. Skip if you want the tracker core only.

---

## 8. Definition of done (Phase 0)

- Cron runs every 15 min on Benten-do without manual intervention.
- All enabled sources' balances land in `tracking.holdings`; new instruments self-register.
- A USD net-worth figure and its time series are correct and charted.
- Stale/unpriced holdings are visibly flagged, not silently zeroed.
- Dashboard is reachable over Tailscale.
- **Codebase contains zero write/order calls to any broker or wallet.** (Verifiable by grep — no order/transaction-sending APIs imported.)

---

## 9. Future extensibility (design-only — do NOT implement now)

These notes exist so Phase 0 doesn't paint the system into a corner. They change *nothing* about what gets built above; they only justify a few cheap schema choices.

- **Reserved `trading` schema.** Live trading, the agent decision log, and order history will live in a separate `trading` schema in the *same* database. Not created in Phase 0. This is why §4 namespaces everything under `tracking`.
- **The `source` + `asset_class` discriminators** already let new feeds (a second broker, another chain, a trading executor's fills) slot in without schema changes.
- **The `instruments` dimension** means future modules reference stable `instrument_id`s rather than re-parsing tickers/addresses — the join that makes a unified portfolio cheap later.
- **Adapter pattern in `sources/`.** A future order-executor or the crypto agent's logger implements the same kind of small, isolated module; the ingester doesn't need to know they exist.
- **Deferred tables (future, not now):** `transactions` (activity history), `decision_log` (agent reasoning, Phase 1), `valuations` with cost-basis/PnL (Phase 2+), `system_control` (kill switch, Phase 2+).
- **Deferred valuation:** Aerodrome LP marking (fees + emissions − impermanent loss) is Phase 1 work; Phase 0 only flags LP positions as unvalued.
- **Dashboard upgrade path:** Streamlit is the Phase 0 choice for speed; a React front-end is a possible later swap once trading views and the agent feed exist.

Anything in this section that starts to feel "needed" for the tracker is a signal that scope is creeping — it isn't.

---

## 10. References

- Umbrella spec: `SYSTEM_SPEC.md` (full multi-phase system; §6 build phases)
- Agentic wallet detail: `wallet_01/PROJECT.md`
- Alpaca Python SDK (`alpaca-py`): https://docs.alpaca.markets/
- web3.py: https://web3py.readthedocs.io/
- CoinGecko API: https://docs.coingecko.com/
- Streamlit: https://docs.streamlit.io/
