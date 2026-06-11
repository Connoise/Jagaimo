"""Trade-ledger sync: import transactions from sources into `tracking.transactions`.

The ledger is an append-only historical *record* of trades and cash events —
deliberately NOT a cost-basis/PnL engine (plan §11 defers that). It is fully
decoupled from the snapshot path: holdings stay authoritative for "what I hold
now"; the ledger answers "what happened, when, at what price".

Two feeds, each isolated so one failing never blocks the other (mirroring the
holdings sources):

  * Vanguard — transaction sections found in the CSV exports under
    VANGUARD_CSV_DIR. Every file is re-scanned each run; the deterministic
    natural key makes overlapping re-exports idempotent. Vanguard only exports
    ~18 months to CSV, so older history is inherently absent.
  * Coinbase — Advanced Trade fills, fetched incrementally from the last
    imported trade timestamp (minus an overlap margin; trade-id dedup makes
    the overlap harmless).
"""

from __future__ import annotations

import logging
from datetime import timedelta

import config
from db import client as db

log = logging.getLogger("jagaimo.ledger")

# Re-fetch window behind the newest imported Coinbase fill, to be safe against
# clock skew / late-arriving fills. Dedup absorbs the overlap.
COINBASE_REFETCH_MARGIN = timedelta(days=1)


def import_vanguard_transactions(conn, settings: config.Config) -> int:
    """Scan every CSV export for transaction sections; insert new rows."""
    from sources.vanguard_csv import (
        _candidate_files,
        parse_export,
        transactions_to_rows,
    )

    def _resolve(symbol: str, asset_class: str) -> int:
        return db.get_or_create_instrument(
            conn, asset_class=asset_class, symbol=symbol
        )

    inserted = 0
    # Oldest first so txn_id/created_at ordering roughly follows trade order.
    for path in reversed(_candidate_files(settings.vanguard_csv_path)):
        try:
            export = parse_export(path.read_text(encoding="utf-8-sig"))
            if not export.transactions:
                continue
            rows = transactions_to_rows(
                export.transactions, resolve_instrument=_resolve
            )
            new = db.insert_transactions(conn, rows)
            inserted += new
            if new:
                log.info("ledger: %s → %d new vanguard transactions",
                         path.name, new)
        except Exception:  # per-file isolation
            log.exception("ledger: vanguard import failed for %s — continuing",
                          path.name)
    return inserted


def import_coinbase_fills(conn, settings: config.Config) -> int:
    """Fetch fills since the last imported one and insert new rows."""
    from sources.coinbase_source import build_coinbase_source

    source = build_coinbase_source(settings)
    if source is None:
        return 0

    since = db.latest_transaction_ts(conn, config.SOURCE_COINBASE)
    if since is not None:
        since -= COINBASE_REFETCH_MARGIN
    rows = source.fetch_fills(since)
    for row in rows:
        if row["symbol"]:
            row["instrument_id"] = db.get_or_create_instrument(
                conn,
                asset_class="crypto_spot",
                symbol=row["symbol"],
                coingecko_id=settings.coinbase_coingecko_id(row["symbol"]),
            )
    inserted = db.insert_transactions(conn, rows)
    if inserted:
        log.info("ledger: %d new coinbase fills", inserted)
    return inserted


def sync_ledger(conn, settings: config.Config) -> dict[str, int]:
    """Run every enabled ledger feed; per-feed isolation. Returns counts."""
    counts: dict[str, int] = {}
    if settings.vanguard_enabled:
        try:
            counts[config.SOURCE_VANGUARD] = import_vanguard_transactions(
                conn, settings
            )
        except Exception:
            log.exception("ledger: vanguard sync failed — continuing")
    if settings.coinbase_enabled:
        try:
            counts[config.SOURCE_COINBASE] = import_coinbase_fills(conn, settings)
        except Exception:
            log.exception("ledger: coinbase sync failed — continuing")
    return counts
