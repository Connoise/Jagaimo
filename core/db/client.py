"""Postgres access for the Jagaimo core (service-role / ingester writes).

Thin helpers over psycopg 3:
  * connection management,
  * idempotent `get_or_create_instrument`,
  * snapshot writers (holdings / net_worth / prices / ohlc_bars),
  * small reads used by the orchestrator and alerters.

The viewer never imports this module — it talks to Supabase's REST API under
RLS. This code path is the privileged ingester role only.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import psycopg
from psycopg.types.json import Json

import config

log = logging.getLogger("jagaimo.db")

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


# ── Connection ───────────────────────────────────────────────────────────────


def connect(database_url: str | None = None) -> psycopg.Connection:
    """Open a connection as the ingester role. Caller manages the lifecycle."""
    url = database_url or config.settings.database_url
    if not url:
        raise config.ConfigError("DATABASE_URL is not set; cannot connect.")
    return psycopg.connect(url, application_name="jagaimo-core")


@contextmanager
def connection(database_url: str | None = None) -> Iterator[psycopg.Connection]:
    """Context-managed connection that commits on success, rolls back on error."""
    conn = connect(database_url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema / seed ────────────────────────────────────────────────────────────


def apply_schema(conn: psycopg.Connection) -> None:
    """Apply db/schema.sql (idempotent)."""
    sql = SCHEMA_PATH.read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    log.info("schema applied from %s", SCHEMA_PATH)


def seed_instruments(conn: psycopg.Connection) -> dict[str, int]:
    """Insert the well-known Base instruments (§2.1). Returns symbol→id."""
    out: dict[str, int] = {}
    for s in config.SEED_INSTRUMENTS:
        out[s.symbol] = get_or_create_instrument(
            conn,
            asset_class=s.asset_class,
            symbol=s.symbol,
            chain=s.chain,
            address=s.address,
            decimals=s.decimals,
            coingecko_id=s.coingecko_id,
            is_stablecoin=s.is_stablecoin,
            display_name=s.display_name,
        )
    return out


# ── Instruments dimension ────────────────────────────────────────────────────


def get_or_create_instrument(
    conn: psycopg.Connection,
    *,
    asset_class: str,
    symbol: str,
    chain: str | None = None,
    address: str | None = None,
    decimals: int | None = None,
    coingecko_id: str | None = None,
    is_stablecoin: bool = False,
    display_name: str | None = None,
) -> int:
    """Resolve (or create) an instrument, returning its id.

    Idempotent on the natural key (asset_class, symbol, chain, address) with
    NULLS NOT DISTINCT, so equities (chain/address NULL) dedupe correctly.
    On conflict, late-arriving metadata (decimals, coingecko_id, …) is filled in
    without clobbering existing non-null values.
    """
    addr = address.lower() if address else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tracking.instruments
                (asset_class, symbol, chain, address, decimals, coingecko_id,
                 is_stablecoin, display_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ON CONSTRAINT instruments_natural_key DO UPDATE SET
                decimals      = COALESCE(tracking.instruments.decimals,
                                         EXCLUDED.decimals),
                coingecko_id  = COALESCE(tracking.instruments.coingecko_id,
                                         EXCLUDED.coingecko_id),
                is_stablecoin = tracking.instruments.is_stablecoin
                                OR EXCLUDED.is_stablecoin,
                display_name  = COALESCE(tracking.instruments.display_name,
                                         EXCLUDED.display_name)
            RETURNING instrument_id
            """,
            (asset_class, symbol, chain, addr, decimals, coingecko_id,
             is_stablecoin, display_name),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


@dataclass(frozen=True)
class InstrumentRow:
    instrument_id: int
    asset_class: str
    symbol: str
    chain: str | None
    address: str | None
    decimals: int | None
    coingecko_id: str | None
    is_stablecoin: bool


def get_instruments(
    conn: psycopg.Connection, ids: Sequence[int] | None = None
) -> list[InstrumentRow]:
    """Fetch instrument rows, optionally restricted to a set of ids."""
    q = (
        "SELECT instrument_id, asset_class, symbol, chain, address, decimals, "
        "coingecko_id, is_stablecoin FROM tracking.instruments"
    )
    params: tuple = ()
    if ids:
        q += " WHERE instrument_id = ANY(%s)"
        params = (list(ids),)
    with conn.cursor() as cur:
        cur.execute(q, params)
        return [InstrumentRow(*r) for r in cur.fetchall()]


# ── Snapshot writers ─────────────────────────────────────────────────────────


def insert_holdings(conn: psycopg.Connection, rows: Iterable[dict[str, Any]]) -> int:
    """Insert holdings rows for a snapshot. Each dict carries the column values."""
    rows = list(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO tracking.holdings
                (snapshot_ts, source, instrument_id, quantity, raw_quantity,
                 price_usd, value_usd, price_as_of, price_status, metadata)
            VALUES (%(snapshot_ts)s, %(source)s, %(instrument_id)s, %(quantity)s,
                    %(raw_quantity)s, %(price_usd)s, %(value_usd)s,
                    %(price_as_of)s, %(price_status)s, %(metadata)s)
            """,
            [{**r, "metadata": Json(r.get("metadata") or {})} for r in rows],
        )
    return len(rows)


def insert_net_worth(
    conn: psycopg.Connection,
    *,
    snapshot_ts: datetime,
    total_usd: Decimal,
    by_source: dict[str, Any],
    by_asset_class: dict[str, Any],
    any_problem: bool,
) -> None:
    """Upsert the net_worth rollup row for this snapshot (idempotent re-run)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tracking.net_worth
                (snapshot_ts, total_usd, by_source, by_asset_class, any_problem)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (snapshot_ts) DO UPDATE SET
                total_usd      = EXCLUDED.total_usd,
                by_source      = EXCLUDED.by_source,
                by_asset_class = EXCLUDED.by_asset_class,
                any_problem    = EXCLUDED.any_problem
            """,
            (snapshot_ts, total_usd, Json(by_source), Json(by_asset_class),
             any_problem),
        )


def insert_prices(conn: psycopg.Connection, rows: Iterable[dict[str, Any]]) -> int:
    """Upsert per-instrument price points (instrument_id, ts) for the tracked set."""
    rows = list(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO tracking.prices (instrument_id, ts, price_usd, price_status)
            VALUES (%(instrument_id)s, %(ts)s, %(price_usd)s, %(price_status)s)
            ON CONFLICT (instrument_id, ts) DO UPDATE SET
                price_usd    = EXCLUDED.price_usd,
                price_status = EXCLUDED.price_status
            """,
            rows,
        )
    return len(rows)


def upsert_ohlc_bars(conn: psycopg.Connection, rows: Iterable[dict[str, Any]]) -> int:
    """Upsert OHLC bars keyed by (instrument_id, timeframe, ts)."""
    rows = list(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO tracking.ohlc_bars
                (instrument_id, timeframe, ts, open, high, low, close, volume)
            VALUES (%(instrument_id)s, %(timeframe)s, %(ts)s, %(open)s, %(high)s,
                    %(low)s, %(close)s, %(volume)s)
            ON CONFLICT (instrument_id, timeframe, ts) DO UPDATE SET
                open = EXCLUDED.open, high = EXCLUDED.high,
                low = EXCLUDED.low, close = EXCLUDED.close,
                volume = EXCLUDED.volume
            """,
            rows,
        )
    return len(rows)


# ── Reads used by orchestrator / alerters ────────────────────────────────────


def get_watchlist_instrument_ids(conn: psycopg.Connection) -> list[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT instrument_id FROM tracking.watchlist")
        return [int(r[0]) for r in cur.fetchall()]


def add_to_watchlist(
    conn: psycopg.Connection, instrument_id: int, note: str | None = None
) -> None:
    """Add an instrument to the watchlist (idempotent)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tracking.watchlist (instrument_id, note) VALUES (%s, %s) "
            "ON CONFLICT (instrument_id) DO NOTHING",
            (instrument_id, note),
        )


@dataclass
class WatchlistRequestRow:
    request_id: int
    kind: str
    symbol: str | None
    chain: str | None
    address: str | None
    note: str | None


def get_pending_watchlist_requests(
    conn: psycopg.Connection,
) -> list[WatchlistRequestRow]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT request_id, kind, symbol, chain, address, note "
            "FROM tracking.watchlist_requests WHERE status = 'pending' "
            "ORDER BY created_at"
        )
        return [WatchlistRequestRow(*r) for r in cur.fetchall()]


def resolve_watchlist_request(
    conn: psycopg.Connection,
    request_id: int,
    *,
    status: str,
    detail: str | None = None,
    instrument_id: int | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tracking.watchlist_requests SET status = %s, detail = %s, "
            "instrument_id = %s, resolved_at = now() WHERE request_id = %s",
            (status, detail, instrument_id, request_id),
        )


def get_tracked_instrument_ids(conn: psycopg.Connection) -> list[int]:
    """Instruments to maintain OHLC for: latest-snapshot holdings ∪ watchlist."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT instrument_id FROM tracking.current_holdings
            UNION
            SELECT instrument_id FROM tracking.watchlist
            """
        )
        return [int(r[0]) for r in cur.fetchall()]


def latest_ohlc_ts(
    conn: psycopg.Connection, instrument_id: int, timeframe: str
) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(ts) FROM tracking.ohlc_bars "
            "WHERE instrument_id = %s AND timeframe = %s",
            (instrument_id, timeframe),
        )
        row = cur.fetchone()
        return row[0] if row else None


@dataclass
class AlertState:
    last_alert_value: Decimal | None
    last_alert_ts: datetime | None


def get_alert_state(conn: psycopg.Connection) -> AlertState:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_alert_value, last_alert_ts FROM tracking.alert_state "
            "WHERE id = 1"
        )
        row = cur.fetchone()
        if not row:
            return AlertState(None, None)
        return AlertState(row[0], row[1])


def update_alert_state(
    conn: psycopg.Connection, value: Decimal, ts: datetime
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tracking.alert_state SET last_alert_value = %s, "
            "last_alert_ts = %s WHERE id = 1",
            (value, ts),
        )


@dataclass
class TargetRow:
    target_id: int
    instrument_id: int
    label: str | None
    target_usd: Decimal
    direction: str
    near_pct: Decimal
    last_state: str
    last_notified: datetime | None


def get_active_targets(conn: psycopg.Connection) -> list[TargetRow]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT target_id, instrument_id, label, target_usd, direction,
                   near_pct, last_state, last_notified
            FROM tracking.price_targets WHERE active = true
            """
        )
        return [TargetRow(*r) for r in cur.fetchall()]


def update_target_state(
    conn: psycopg.Connection, target_id: int, state: str, notified_ts: datetime | None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tracking.price_targets SET last_state = %s, "
            "last_notified = COALESCE(%s, last_notified) WHERE target_id = %s",
            (state, notified_ts, target_id),
        )


def get_latest_prices(conn: psycopg.Connection) -> dict[int, Decimal]:
    """instrument_id → latest known price_usd (skips NULL prices)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_id, price_usd FROM tracking.latest_prices "
            "WHERE price_usd IS NOT NULL"
        )
        return {int(r[0]): r[1] for r in cur.fetchall()}


# ── CLI: apply schema + seed (used by D1 verification) ───────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Jagaimo DB admin")
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()

    config.settings.require("database_url")
    with connection() as _conn:
        if args.apply_schema:
            apply_schema(_conn)
        if args.seed:
            ids = seed_instruments(_conn)
            log.info("seeded instruments: %s", ids)
        if not (args.apply_schema or args.seed):
            with _conn.cursor() as c:
                c.execute("SELECT count(*) FROM tracking.instruments")
                log.info("instruments in DB: %s", c.fetchone()[0])
