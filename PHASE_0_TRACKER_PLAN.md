# Phase 0 — Unified Asset Tracker & Viewer — Development Plan

> **Build scope:** **read-only.** Two layers:
> 1. **Data core** (Python, frontend-agnostic) — snapshots holdings, tracks prices for held *and* watchlisted instruments, maintains OHLC history, evaluates price-target and net-worth alerts.
> 2. **Viewer** (**React**) — an interactive front-end with multi-timeframe charts, candlesticks, point-in-time analytics, overlays, groups, statistical analysis, and target management. Reads/writes the database through self-hosted Supabase's API over the private network.
>
> **No trading, no order placement, no agent logic.** Price targets and alerts are *read-only monitoring* — they notify; they never trade.
>
> Larger trading system: §11 only (forward-compat notes; they add no features here).

**Host:** a Linux host (Ubuntu, no GPU) · **Store:** self-hosted Supabase (Postgres) · **Core:** Python · **Viewer:** React (Vite + TypeScript) · **Access:** private network only (tailnet ACL is the access control)

---

## 1. What this build is (and is not)

**Is:**
- A scheduled ingester reading holdings from three sources, valuing everything in USD.
- A price + OHLC store for every held or watchlisted instrument (basis for all instrument-level charts).
- Server-side evaluation of price targets and net-worth-change alerts (two Telegram targets).
- A React viewer delivering the eight features in §6.

**Is NOT (do not build in Phase 0):**
- Any order/trade execution or write calls to a broker or wallet.
- Backtrader, strategy rules, or trade-signal generation.
- The crypto agent's decision loop or decision-log population.
- A kill switch / `trading_enabled` enforcement.
- Paper↔live promotion logic.

Price targets are **alerts only** — if a task starts wiring a target to an order, it is out of scope.

---

## 2. Resolved build decisions (locked — do not re-open)

1. **Crypto pricing is by contract address**: CoinGecko `/simple/token_price/base` for ERC-20s, `/simple/price?ids=ethereum` for native ETH. `coingecko_id` is metadata only. Unlisted new token → mark `unpriced`, never fail the run. Pre-seed USDC/WETH/AERO so day-one pricing works.
2. **Price state is an enum, not a boolean.** `price_status ∈ {live, last_close, stale_unlisted, unpriced}`. A closed-market equity is `last_close` (correct value, shown normally, **not** a problem); only `stale_unlisted`/`unpriced` are problems and drive the "issues" indicator and alerts.
3. **No retention pruning in Phase 0.** ~1k holdings rows/day is trivial for Postgres. The portfolio chart reads the small `net_worth` rollup; `holdings` is read only for the latest snapshot. Downsampling >90 days is a future option.
4. **Net-worth alert (Q4):** fire when total moves **>5%** *and* **>$25** since the **last alerted** value (persisted in `alert_state`), **60-min cooldown**. 5%/$25/60-min are tunable constants.
5. **Native-ETH sentinel:** constant `0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE` (avoids the zero address), `chain=base`, `symbol=ETH`, `coingecko_id=ethereum`, `decimals=18`. Defined once in `config.py`.
6. **Token discovery:** primary path = **Alchemy `alchemy_getTokenBalances` + `alchemy_getTokenMetadata`** (filter the spam flag to drop airdropped scams). Fallback (public RPC + web3.py) requires a configured **`TOKEN_ALLOWLIST`** + per-token `balanceOf`. Native via `eth_getBalance`.
7. **Market calendar:** Alpaca `/v2/clock` + `/v2/calendar` are the single source of truth — never hand-roll NYSE hours. Open → equities `live`; closed → `last_close`. Store all timestamps **UTC**; convert to local only in the viewer.
8. **Secrets (Q8):** plaintext `.env` is acceptable **with** `chmod 600`, `.env` gitignored, and a **least-privilege Postgres "ingester" role** scoped to the `tracking` schema. Real secrets are `DATABASE_URL` and Alpaca keys; wallet addresses are public. (Browser/viewer access is governed by RLS — §4.)
9. **Stablecoins priced live**, not pinned to $1 — hiding a depeg defeats the tracker; rounding is sub-basis-point. `is_stablecoin` is for display grouping; round the *display* to cents if desired.
10. **Portfolio history is forward-only — accepted.** The net-worth chart starts empty at first run and fills going forward (past holdings are unknowable). The viewer labels short ranges honestly ("tracking since <date>"); it does **not** fabricate pre-tracking portfolio data. (Instrument charts are unaffected — they backfill, §5.)
11. **Viewer = React** (committed). Built with Vite + TypeScript, reads/writes via Supabase's auto REST/realtime API over the tailnet. Production: static build served by a static server (Caddy/nginx) as a **systemd** service bound to the private interface. **No app-level auth** (single user); the tailnet ACL is the access control.

---

## 3. Sources & valuation

All sources **read-only**. Each wallet is just an address handed to the same EVM adapter.

| Source key | Reads | How | Live pricing |
|---|---|---|---|
| `alpaca` | equity/ETF positions + cash | `alpaca-py`, account/positions + clock/calendar (never orders) | last trade if open, else `last_close` |
| `wallet_standard` | ERC-20 + native (Base) | Alchemy `getTokenBalances`/`getTokenMetadata` (or public RPC + `TOKEN_ALLOWLIST`) | CoinGecko by contract |
| `wallet_01` | ERC-20 + native (Base) — agentic wallet, address via `WALLET_01_ADDRESS` env | same EVM adapter | CoinGecko by contract |

**Historical OHLC** (for candlesticks + year/all-time on the instrument path):
- Equities/ETFs → **Alpaca historical bars** (1h + 1d).
- Native ETH / major coins → **CoinGecko OHLC by id**.
- Base tokens (AERO, etc.) → **GeckoTerminal** OHLCV by token address on Base (verify current free-tier endpoints/limits).

Notes:
- **Alpaca optional at runtime** — no account/positions → equities source contributes nothing; tracker runs on wallets alone. Degrade gracefully, never error.
- **LP positions deferred** — fungible spot only; an Aerodrome LP token is `unpriced`, labeled "LP — Phase 1."
- Cache prices within a run; the tracked set is small, so free tiers are ample.

---

## 4. Data model (`tracking` schema)

```sql
CREATE SCHEMA IF NOT EXISTS tracking;

CREATE TYPE tracking.price_status AS ENUM ('live','last_close','stale_unlisted','unpriced');

-- Dimension: one row per distinct instrument ever seen (held OR watchlisted).
CREATE TABLE tracking.instruments (
    instrument_id BIGSERIAL PRIMARY KEY,
    asset_class   TEXT NOT NULL,            -- 'equity'|'etf'|'crypto_spot'|'crypto_lp'
    symbol        TEXT NOT NULL,
    chain         TEXT,                     -- NULL equities; 'base' crypto
    address       TEXT,                     -- NULL equities; contract or native sentinel
    decimals      INT,
    coingecko_id  TEXT,                     -- metadata; ERC-20s priced by contract
    is_stablecoin BOOLEAN NOT NULL DEFAULT false,
    display_name  TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset_class, symbol, chain, address)
);

-- Fact: holdings per snapshot, valued in USD.
CREATE TABLE tracking.holdings (
    id            BIGSERIAL PRIMARY KEY,
    snapshot_ts   TIMESTAMPTZ NOT NULL,
    source        TEXT NOT NULL,            -- 'alpaca'|'wallet_standard'|'wallet_01'
    instrument_id BIGINT NOT NULL REFERENCES tracking.instruments(instrument_id),
    quantity      NUMERIC(78,30) NOT NULL,
    raw_quantity  NUMERIC(78,0),
    price_usd     NUMERIC(38,18),
    value_usd     NUMERIC(38,18),
    price_as_of   TIMESTAMPTZ,
    price_status  tracking.price_status NOT NULL DEFAULT 'unpriced',
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX ON tracking.holdings (snapshot_ts);
CREATE INDEX ON tracking.holdings (source, snapshot_ts);
CREATE INDEX ON tracking.holdings (instrument_id, snapshot_ts);

-- Rollup: cheap net-worth time series (the portfolio chart's source).
CREATE TABLE tracking.net_worth (
    snapshot_ts    TIMESTAMPTZ PRIMARY KEY,
    total_usd      NUMERIC(38,18) NOT NULL,
    by_source      JSONB NOT NULL,
    by_asset_class JSONB NOT NULL,
    any_problem    BOOLEAN NOT NULL DEFAULT false
);

-- Per-instrument price series for HELD + WATCHLISTED instruments.
CREATE TABLE tracking.prices (
    instrument_id BIGINT NOT NULL REFERENCES tracking.instruments(instrument_id),
    ts            TIMESTAMPTZ NOT NULL,
    price_usd     NUMERIC(38,18),
    price_status  tracking.price_status NOT NULL DEFAULT 'unpriced',
    PRIMARY KEY (instrument_id, ts)
);

-- Backfilled + maintained candles for instrument candlesticks and long-range views.
CREATE TABLE tracking.ohlc_bars (
    instrument_id BIGINT NOT NULL REFERENCES tracking.instruments(instrument_id),
    timeframe     TEXT NOT NULL,            -- '1h' | '1d'
    ts            TIMESTAMPTZ NOT NULL,     -- bar open
    open NUMERIC(38,18), high NUMERIC(38,18), low NUMERIC(38,18), close NUMERIC(38,18),
    volume NUMERIC(38,18),
    PRIMARY KEY (instrument_id, timeframe, ts)
);

-- ── User config (the ONLY tables the browser/viewer may write) ──────────────

CREATE TABLE tracking.watchlist (
    instrument_id BIGINT PRIMARY KEY REFERENCES tracking.instruments(instrument_id),
    added_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    note          TEXT
);

CREATE TABLE tracking.instrument_groups (
    group_id   BIGSERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE tracking.group_members (
    group_id      BIGINT NOT NULL REFERENCES tracking.instrument_groups(group_id) ON DELETE CASCADE,
    instrument_id BIGINT NOT NULL REFERENCES tracking.instruments(instrument_id),
    weight        NUMERIC(20,8) NOT NULL DEFAULT 1.0,
    PRIMARY KEY (group_id, instrument_id)
);

CREATE TABLE tracking.price_targets (
    target_id     BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES tracking.instruments(instrument_id),
    label         TEXT,
    target_usd    NUMERIC(38,18) NOT NULL,
    direction     TEXT NOT NULL,            -- 'above' | 'below'
    near_pct      NUMERIC(6,3) NOT NULL DEFAULT 2.0,
    active        BOOLEAN NOT NULL DEFAULT true,
    last_state    TEXT NOT NULL DEFAULT 'far',  -- 'far'|'near'|'hit' (de-dup)
    last_notified TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Alerter state ───────────────────────────────────────────────────────────

-- Single-row state for the net-worth threshold alerter (Q4).
CREATE TABLE tracking.alert_state (
    id               INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_alert_value NUMERIC(38,18),
    last_alert_ts    TIMESTAMPTZ
);
INSERT INTO tracking.alert_state (id) VALUES (1) ON CONFLICT DO NOTHING;

-- ── Convenience views (one-liner reads for the viewer) ──────────────────────

-- Latest completed snapshot's holdings (net_worth row marks run completion).
CREATE VIEW tracking.current_holdings AS
SELECT h.*
FROM tracking.holdings h
JOIN (SELECT max(snapshot_ts) AS ts FROM tracking.net_worth) m
  ON h.snapshot_ts = m.ts;

-- Most recent price per instrument (distance-to-target, overview prices).
CREATE VIEW tracking.latest_prices AS
SELECT DISTINCT ON (instrument_id) instrument_id, ts, price_usd, price_status
FROM tracking.prices
ORDER BY instrument_id, ts DESC;
```

`get_or_create` instruments on ingest so new tokens/tickers self-register. Held-instrument prices appear in both `holdings.price_usd` (valuation) and `prices` (unified series) — a small, deliberate denormalization that keeps instrument-level queries clean. `tracking since` = `min(snapshot_ts)` from `net_worth`.

### Access model (two write principals)

- **Ingester** → Postgres **service role**: full write on all `tracking` tables. Used only by the Python core.
- **Viewer (browser)** → Supabase **anon role** via the API, constrained by **RLS**:
  - `SELECT` on **all** `tracking` tables/views.
  - `INSERT/UPDATE/DELETE` **only** on `watchlist`, `instrument_groups`, `group_members`, `price_targets` (user config).
  - **No writes** to `instruments`, `holdings`, `prices`, `net_worth`, `ohlc_bars`, `alert_state`.

Enable RLS on every `tracking` table; add a permissive `SELECT` policy for anon everywhere and write policies for anon only on the four config tables. On a single-user tailnet this is defense-in-depth (the anon key already only reaches the host over the private network), but it guarantees the browser key can never corrupt ingester-owned data.

---

## 5. Two data paths & history horizons (settled)

Every view draws from one path; their history horizons differ by design.

- **Portfolio path** — `net_worth` + `holdings`/`current_holdings`. **Forward-only**, starts empty at first run (decision §2.10). Powers: net-worth chart, per-source/asset breakdown, point-in-time portfolio analytics, portfolio candlesticks (derived from intra-period snapshots).
- **Instrument path** — `prices` + `ohlc_bars`. **Backfilled from APIs**, so it has real multi-year history immediately. Powers: instrument line/candlestick charts, overlays, groups, ROC/volatility/drawdown analysis, target evaluation.

Viewer rule: when a requested timeframe exceeds available portfolio history, show what exists and label it "tracking since <date>" — never fabricate. Instrument timeframes are bounded only by backfill depth.

---

## 6. Viewer features (React)

Spec'd by behavior + data path + metric. Recommended libraries: **lightweight-charts** (TradingView) for time-series/candlestick/overlay; **Recharts** (or Plotly) for statistical/analysis charts; **@supabase/supabase-js** for data; **@tanstack/react-query** for fetching/caching.

**F1 — Timeframe switcher** (`hour | day | week | month | year | all`). Segmented control re-queries the active series. Portfolio from `net_worth` (resampled); instruments from `prices`/`ohlc_bars`. Honors §5.

**F2 — Selectable points / hover values.** Crosshair + hover everywhere; click pins a timestamp and reveals exact values. *lightweight-charts crosshair + `subscribeClick`.*

**F3 — Point-in-time analytics.** A time picker (or a pinned F2 point) sets a reference timestamp; show holdings + net worth **as of the nearest snapshot** plus deltas vs now. Query `holdings`/`net_worth WHERE snapshot_ts <= chosen ORDER BY ts DESC LIMIT 1`.

**F4 — Candlestick toggle.** Instruments: from `ohlc_bars` at the matching timeframe. Portfolio: derive OHLC from intra-period snapshots (open=first, high=max, low=min, close=last) — meaningful only at timeframes ≥ snapshot interval, from tracker start. *lightweight-charts candlestick series.*

**F5 — Overlay multiple instruments + watchlist.** Multiselect → multiple **normalized** traces (index to 100 at window start, or % change) so different price scales compare. Watchlist add/remove UI lives here and begins pricing the instrument on the next run. Instrument path.

**F6 — Groups (basket as one series).** CRUD over `instrument_groups`/`group_members` (optional weights). Group series = weighted sum (absolute) or normalized basket index; behaves like a synthetic instrument in F1–F4.

**F7 — Analysis views (descriptive only).** Computed client-side over the selected window: **rate of change** (% + rolling line), **volatility** (rolling stdev of returns, optionally annualized), **max drawdown** (peak-to-trough), **returns histogram**; *optional* correlation matrix / beta vs a benchmark (e.g. SPY). These describe past behavior — **not** predictions or advice.

**F8 — Price targets.** CRUD over `price_targets` (instrument, target, above/below, near band %); shows current distance-to-target. **Evaluation runs server-side** in the core (D6); this view only manages targets. Alerts: **near** → Telegram log channel, **hit/crossed** → urgent channel, de-duped via `last_state` + cooldown.

---

## 7. Project structure

```
asset-tracker/
├── core/                              # Python data core
│   ├── .env.example
│   ├── .gitignore                     # MUST list .env
│   ├── requirements.txt
│   ├── config.py                      # env + constants: SNAPSHOT_INTERVAL, NATIVE_ETH_SENTINEL,
│   │                                  #   NETWORTH_ALERT_PCT/USD/COOLDOWN, TOKEN_ALLOWLIST
│   ├── db/
│   │   ├── schema.sql                 # §4 DDL (tables, views, RLS policies)
│   │   └── client.py                  # psycopg + get_or_create_instrument + writers (service role)
│   ├── sources/
│   │   ├── base.py                    # Holding dataclass + Source protocol
│   │   ├── alpaca_source.py           # positions + clock/calendar (read-only)
│   │   └── evm_source.py              # Alchemy discovery (+ allowlist fallback); native balance
│   ├── pricing/
│   │   ├── coingecko.py               # contract + native pricing; stablecoins live
│   │   └── ohlc.py                    # backfill/maintain ohlc_bars (Alpaca/CoinGecko/GeckoTerminal)
│   ├── alerts/
│   │   └── telegram.py                # two targets: log + urgent
│   ├── targets.py                     # price-target evaluation (called by ingest)
│   ├── ingest.py                      # ORCHESTRATOR + cron entrypoint
│   └── tests/
│       └── test_sources.py
└── viewer/                            # React (Vite + TS) — reads/writes Supabase over the tailnet
    ├── .env                           # gitignored: VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── lib/supabase.ts            # supabase-js client (tracking schema)
        ├── hooks/                     # react-query hooks: useNetWorth, usePrices, useHoldings, useTargets…
        └── components/
            ├── TimeframeSwitcher.tsx          # F1
            ├── NetWorthChart.tsx              # portfolio line/candles
            ├── InstrumentChart.tsx            # F2/F4 line+candlestick, click-to-pin
            ├── PointInTimePanel.tsx           # F3
            ├── OverlayChart.tsx               # F5 normalized multi-series
            ├── WatchlistManager.tsx           # F5 watchlist CRUD
            ├── GroupManager.tsx               # F6 groups CRUD + series
            ├── AnalysisPanel.tsx              # F7 (Recharts)
            └── TargetsManager.tsx             # F8 targets CRUD + distance
```

**Core env (`core/.env.example`):**
```
DATABASE_URL=postgresql://...            # least-privilege ingester role, tracking schema
ALPACA_API_KEY_ID=                       # optional — omit to skip equities
ALPACA_API_SECRET_KEY=
ALPACA_BASE_URL=https://api.alpaca.markets
ALCHEMY_API_KEY=                         # or set BASE_RPC_URL + TOKEN_ALLOWLIST
BASE_RPC_URL=
WALLET_STANDARD_ADDRESS=
WALLET_01_ADDRESS=
COINGECKO_API_KEY=                       # free tier; demo key optional
TELEGRAM_BOT_TOKEN=
TELEGRAM_LOG_CHAT_ID=
TELEGRAM_ALERT_CHAT_ID=
```
**Viewer env (`viewer/.env`):** `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (anon key constrained by RLS — §4).

---

## 8. Ingestion flow (`core/ingest.py`)

One idempotent run, safe every 15 min:

1. `snapshot_ts = now()` (UTC) for the whole run.
2. Query Alpaca clock once → market open/closed.
3. For each **enabled** source, `fetch_holdings()` → resolve instruments → write valued `holdings` rows (equities `live`/`last_close`; crypto by contract).
4. Tracked set = held ∪ `watchlist`. Price the tracked set → write `prices` rows (stablecoins live).
5. Compute + write the `net_worth` rollup (`any_problem` = any `stale_unlisted`/`unpriced`).
6. Evaluate `price_targets` vs latest prices → near/hit notifications, de-duped via `last_state` + cooldown.
7. Net-worth alert: >5% **and** >$25 vs `alert_state.last_alert_value`, 60-min cooldown; update `alert_state` on fire.
8. One-line log summary; **per-source isolation** — one source failing must not abort the rest.

**OHLC maintenance** (`pricing/ohlc.py`, from ingest or a daily job): on first sighting / watchlist-add, backfill `ohlc_bars` (1h+1d) from §3 sources; thereafter append latest (1d daily, 1h hourly). CoinGecko free OHLC is coarse over long ranges (daily) — acceptable.

**Cron (ingestion host):**
```
*/15 * * * * cd /path/to/asset-tracker/core && .venv/bin/python ingest.py >> ingest.log 2>&1
```

---

## 9. Build milestones

Build and verify the **core (D-series) first** — it is frontend-independent — then the **viewer (V-series)**.

**Core**
- **D0 — Skeleton & config.** Structure, deps, `config.py` (native sentinel + thresholds), `.gitignore` with `.env`. *Done:* `import config` loads cleanly; missing required vars error clearly.
- **D1 — DB.** Full §4 schema (enum, tables, views, RLS policies) applied; `client.py` connects as the ingester role; `get_or_create_instrument` idempotent. *Done:* all objects exist; an instrument round-trips; anon role can read but cannot write data tables.
- **D2 — EVM source.** Alchemy discovery + metadata (+ allowlist fallback); native via `eth_getBalance`; spam filtered. *Done:* `wallet_01` balances match Basescan to the token.
- **D3 — Pricing.** Contract + native pricing, live stablecoins, per-run cache. *Done:* USDC ≈ $1 (live), ETH/AERO plausible.
- **D4 — Alpaca source.** Positions + clock/calendar; `live`/`last_close` correct; empty/absent account degrades gracefully. *Done:* matches Alpaca dashboard, or empty cleanly with no creds.
- **D5 — Orchestrator.** Holdings + watchlist prices + `net_worth`; per-source isolation. *Done:* a manual run populates `holdings`, `prices`, `net_worth`; totals foot; `price_status` correct.
- **D6 — Alerts.** `targets.py` + `alerts/telegram.py`: target near/hit + net-worth threshold via `alert_state`, de-duped, two channels. *Done:* a simulated near and a simulated hit fire the right channels once (no repeat next run).
- **D7 — OHLC.** Backfill + maintain `ohlc_bars` (1h/1d) for held + watchlisted instruments. *Done:* a stock and a token each have multi-month daily + recent hourly bars.
- **D8 — Schedule & harden.** Cron; ingester role enforced; structured logging; README. *Done:* runs unattended an hour with a growing series; killing one source still yields a partial snapshot + clear log.

**Viewer (React)**
- **V0 — Scaffold.** Vite + React + TS; `lib/supabase.ts`; react-query; render `net_worth` as a raw line. *Done:* chart shows live net worth from the DB over the tailnet.
- **V1 — Portfolio overview.** Net-worth line + by-source/asset breakdown + `current_holdings` table + `price_status` labeling ("equities at last close / N issues"). *Done:* renders from DB.
- **V2 — Timeframes (F1).** *Done:* all six windows work; over-long portfolio ranges show "tracking since <date>".
- **V3 — Selection + point-in-time (F2, F3).** *Done:* clicking a point shows as-of holdings + deltas.
- **V4 — Candlesticks (F4).** *Done:* instrument candles render from `ohlc_bars`; portfolio candles derive from snapshots.
- **V5 — Overlays + watchlist (F5).** *Done:* ≥2 instruments overlay normalized; watchlist add/remove persists and starts pricing next run.
- **V6 — Groups (F6).** *Done:* a weighted group renders as one series across timeframes.
- **V7 — Analysis (F7).** *Done:* ROC, rolling volatility, max drawdown, returns histogram compute over the window.
- **V8 — Targets UI (F8).** *Done:* targets CRUD persists, distance-to-target shows; alerts continue from D6.
- **V9 — Build & serve.** Static build behind Caddy/nginx as a systemd service bound to the private interface; *(optional)* Supabase realtime for live-updating charts. *Done:* production bundle served over the tailnet; RLS enforced; no app auth.

---

## 10. Definition of done (Phase 0)

**Core:** cron runs every 15 min unattended; `holdings`/`prices`/`net_worth`/`ohlc_bars` populate; instruments self-register; targets + net-worth alerts fire and de-dupe; **zero write/order calls to any broker or wallet** (grep-verifiable). 
**Viewer:** F1–F8 functional against the DB over the private network; RLS confines the browser to reading data + writing only config tables; portfolio history starts empty and is labeled honestly; analytics are descriptive only.

---

## 11. Future extensibility (design-only — do NOT implement now)

- **Reserved `trading` schema** in the same DB for live trading, order history, and the agent decision log — not created here. This is why everything is namespaced `tracking`.
- **`source` + `asset_class` discriminators** let new feeds (second broker, another chain, a trade executor's fills) slot in without schema changes.
- **`instruments` + `prices`/`ohlc_bars`** give later modules a stable id and shared history.
- **Adapter pattern in `sources/`** — a future order-executor or the agent logger is just another isolated module.
- **Deferred:** Aerodrome LP marking (Phase 1); cost-basis/PnL + wash-sale tracking (Phase 2+); `system_control` kill switch (Phase 2+); intraday-from-`prices` crypto candles if finer-than-API granularity is ever needed.
- **Realtime polish:** Supabase realtime → live-updating React charts (optional).

Anything here that starts to feel "needed" for the tracker is scope creep — it isn't.

---

## 12. References
- Umbrella spec: `SYSTEM_SPEC.md` — local companion doc.
- Alpaca Python SDK (`alpaca-py`): https://docs.alpaca.markets/
- web3.py: https://web3py.readthedocs.io/ · Alchemy token APIs: https://docs.alchemy.com/
- CoinGecko: https://docs.coingecko.com/ · GeckoTerminal: https://www.geckoterminal.com/dex-api
- React + Vite: https://vitejs.dev/ · Supabase JS: https://supabase.com/docs/reference/javascript
- TradingView lightweight-charts: https://github.com/tradingview/lightweight-charts · Recharts: https://recharts.org/ · TanStack Query: https://tanstack.com/query
