-- ─────────────────────────────────────────────────────────────────────────────
-- Jagaimo — Phase 0 `tracking` schema (plan §4)
-- Idempotent: safe to re-run. Apply with `python -m db.client --apply-schema`
-- or `psql "$DATABASE_URL" -f db/schema.sql`.
-- All timestamps are UTC.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS tracking;

-- price_status enum (decision §2.2). Guarded so re-runs don't error.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typname = 'price_status' AND n.nspname = 'tracking'
    ) THEN
        CREATE TYPE tracking.price_status AS ENUM
            ('live', 'last_close', 'stale_unlisted', 'unpriced');
    END IF;
END$$;

-- ── Dimension: one row per distinct instrument ever seen (held OR watchlisted) ─
CREATE TABLE IF NOT EXISTS tracking.instruments (
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
    -- NULLS NOT DISTINCT so equities (chain/address NULL) dedupe correctly.
    -- Without this, Postgres treats each NULL as distinct and the same ticker
    -- would self-register on every run.
    CONSTRAINT instruments_natural_key
        UNIQUE NULLS NOT DISTINCT (asset_class, symbol, chain, address)
);

-- ── Fact: holdings per snapshot, valued in USD ───────────────────────────────
CREATE TABLE IF NOT EXISTS tracking.holdings (
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
CREATE INDEX IF NOT EXISTS holdings_snapshot_idx
    ON tracking.holdings (snapshot_ts);
CREATE INDEX IF NOT EXISTS holdings_source_snapshot_idx
    ON tracking.holdings (source, snapshot_ts);
CREATE INDEX IF NOT EXISTS holdings_instrument_snapshot_idx
    ON tracking.holdings (instrument_id, snapshot_ts);

-- ── Rollup: cheap net-worth time series (the portfolio chart's source) ───────
CREATE TABLE IF NOT EXISTS tracking.net_worth (
    snapshot_ts    TIMESTAMPTZ PRIMARY KEY,
    total_usd      NUMERIC(38,18) NOT NULL,
    by_source      JSONB NOT NULL,
    by_asset_class JSONB NOT NULL,
    any_problem    BOOLEAN NOT NULL DEFAULT false
);

-- ── Per-instrument price series for HELD + WATCHLISTED instruments ───────────
CREATE TABLE IF NOT EXISTS tracking.prices (
    instrument_id BIGINT NOT NULL REFERENCES tracking.instruments(instrument_id),
    ts            TIMESTAMPTZ NOT NULL,
    price_usd     NUMERIC(38,18),
    price_status  tracking.price_status NOT NULL DEFAULT 'unpriced',
    PRIMARY KEY (instrument_id, ts)
);

-- ── Backfilled + maintained candles for instrument candlesticks / long range ─
CREATE TABLE IF NOT EXISTS tracking.ohlc_bars (
    instrument_id BIGINT NOT NULL REFERENCES tracking.instruments(instrument_id),
    timeframe     TEXT NOT NULL,            -- '1h' | '1d'
    ts            TIMESTAMPTZ NOT NULL,     -- bar open
    open   NUMERIC(38,18),
    high   NUMERIC(38,18),
    low    NUMERIC(38,18),
    close  NUMERIC(38,18),
    volume NUMERIC(38,18),
    PRIMARY KEY (instrument_id, timeframe, ts)
);

-- ── User config (the ONLY tables the browser/viewer may write) ───────────────

CREATE TABLE IF NOT EXISTS tracking.watchlist (
    instrument_id BIGINT PRIMARY KEY REFERENCES tracking.instruments(instrument_id),
    added_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    note          TEXT
);

CREATE TABLE IF NOT EXISTS tracking.instrument_groups (
    group_id   BIGSERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tracking.group_members (
    group_id      BIGINT NOT NULL
        REFERENCES tracking.instrument_groups(group_id) ON DELETE CASCADE,
    instrument_id BIGINT NOT NULL REFERENCES tracking.instruments(instrument_id),
    weight        NUMERIC(20,8) NOT NULL DEFAULT 1.0,
    PRIMARY KEY (group_id, instrument_id)
);

CREATE TABLE IF NOT EXISTS tracking.price_targets (
    target_id     BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL REFERENCES tracking.instruments(instrument_id),
    label         TEXT,
    target_usd    NUMERIC(38,18) NOT NULL,
    direction     TEXT NOT NULL,            -- 'above' | 'below'
    near_pct      NUMERIC(6,3) NOT NULL DEFAULT 2.0,
    active        BOOLEAN NOT NULL DEFAULT true,
    last_state    TEXT NOT NULL DEFAULT 'far',  -- 'far'|'near'|'hit' (de-dup)
    last_notified TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT price_targets_direction_chk CHECK (direction IN ('above', 'below'))
);

-- Browser-submitted requests to start tracking a NEW instrument the system has
-- not seen yet (a stock ticker, or a token by contract address). The browser
-- cannot write `instruments` directly (RLS), so it enqueues a request here; the
-- ingester resolves each one into an instrument + watchlist entry on its next
-- run, then marks it resolved/error. Keeps the access model intact.
CREATE TABLE IF NOT EXISTS tracking.watchlist_requests (
    request_id    BIGSERIAL PRIMARY KEY,
    kind          TEXT NOT NULL,            -- 'equity' | 'token'
    symbol        TEXT,                     -- ticker (equity) / display symbol (token)
    chain         TEXT,                     -- token chain (default 'base')
    address       TEXT,                     -- token contract address
    note          TEXT,
    status        TEXT NOT NULL DEFAULT 'pending', -- 'pending'|'resolved'|'error'
    detail        TEXT,                     -- resolution note / error message
    instrument_id BIGINT REFERENCES tracking.instruments(instrument_id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ,
    CONSTRAINT watchlist_requests_kind_chk CHECK (kind IN ('equity', 'token')),
    CONSTRAINT watchlist_requests_status_chk
        CHECK (status IN ('pending', 'resolved', 'error'))
);
CREATE INDEX IF NOT EXISTS watchlist_requests_pending_idx
    ON tracking.watchlist_requests (status) WHERE status = 'pending';

-- ── Alerter state ────────────────────────────────────────────────────────────

-- Single-row state for the net-worth threshold alerter (decision §2.4).
CREATE TABLE IF NOT EXISTS tracking.alert_state (
    id               INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_alert_value NUMERIC(38,18),
    last_alert_ts    TIMESTAMPTZ
);
INSERT INTO tracking.alert_state (id) VALUES (1) ON CONFLICT DO NOTHING;

-- ── Convenience views (one-liner reads for the viewer) ───────────────────────

-- Latest completed snapshot's holdings (net_worth row marks run completion).
CREATE OR REPLACE VIEW tracking.current_holdings AS
SELECT h.*
FROM tracking.holdings h
JOIN (SELECT max(snapshot_ts) AS ts FROM tracking.net_worth) m
  ON h.snapshot_ts = m.ts;

-- Most recent price per instrument (distance-to-target, overview prices).
CREATE OR REPLACE VIEW tracking.latest_prices AS
SELECT DISTINCT ON (instrument_id) instrument_id, ts, price_usd, price_status
FROM tracking.prices
ORDER BY instrument_id, ts DESC;

-- ─────────────────────────────────────────────────────────────────────────────
-- Row-Level Security (access model §4): the browser anon role may SELECT all
-- tracking tables but may only write the four user-config tables. The ingester
-- connects as a privileged role (BYPASSRLS or table owner) and is unaffected.
--
-- This block is guarded on the `anon` role existing (it always does on
-- Supabase). On a plain Postgres without Supabase roles it is skipped, so the
-- schema still applies for local/dev testing.
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    read_tables  TEXT[] := ARRAY[
        'instruments','holdings','net_worth','prices','ohlc_bars',
        'watchlist','instrument_groups','group_members','price_targets',
        'watchlist_requests','alert_state'
    ];
    write_tables TEXT[] := ARRAY[
        'watchlist','instrument_groups','group_members','price_targets',
        'watchlist_requests'
    ];
    t TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        RAISE NOTICE 'Role "anon" not found — skipping RLS policy setup (non-Supabase env).';
        RETURN;
    END IF;

    GRANT USAGE ON SCHEMA tracking TO anon;

    -- Enable RLS + permissive SELECT for anon on every tracking table.
    -- Plain ENABLE (not FORCE): the table-owning ingester role bypasses RLS and
    -- writes freely, while anon is fully constrained by the policies below.
    FOREACH t IN ARRAY read_tables LOOP
        EXECUTE format('ALTER TABLE tracking.%I ENABLE ROW LEVEL SECURITY;', t);
        EXECUTE format('GRANT SELECT ON tracking.%I TO anon;', t);
        EXECUTE format($f$
            DROP POLICY IF EXISTS %1$s_anon_select ON tracking.%1$I;
            CREATE POLICY %1$s_anon_select ON tracking.%1$I
                FOR SELECT TO anon USING (true);
        $f$, t);
    END LOOP;

    -- Write policies (INSERT/UPDATE/DELETE) for anon on user-config tables only.
    FOREACH t IN ARRAY write_tables LOOP
        EXECUTE format('GRANT INSERT, UPDATE, DELETE ON tracking.%I TO anon;', t);
        EXECUTE format($f$
            DROP POLICY IF EXISTS %1$s_anon_write ON tracking.%1$I;
            CREATE POLICY %1$s_anon_write ON tracking.%1$I
                FOR ALL TO anon USING (true) WITH CHECK (true);
        $f$, t);
    END LOOP;

    -- Sequences backing the writable config tables need USAGE for inserts.
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA tracking TO anon;
END$$;
