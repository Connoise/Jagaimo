"""Jagaimo ingestion orchestrator — the cron entrypoint.

One idempotent run (plan §8):
  1. snapshot_ts = now() (UTC) for the whole run.
  2. collect holdings from every enabled source (per-source isolation).
  3. get_or_create instruments; price crypto via CoinGecko (equities arrive
     pre-priced from Alpaca).
  4. write holdings; price the tracked set (held ∪ watchlist) into `prices`.
  5. compute + write the net_worth rollup.
  6. evaluate price targets + the net-worth threshold alert (D6).
  7. maintain OHLC bars for held ∪ watchlist (D7).

A failure in one source must never abort the others. Exit non-zero only on a
hard failure (e.g. DB unreachable) so cron surfaces it.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import config
from db import client as db
from sources.base import Holding

log = logging.getLogger("jagaimo.ingest")

SENTINEL = config.NATIVE_ETH_SENTINEL.lower()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RunResult:
    snapshot_ts: datetime
    holdings_written: int = 0
    prices_written: int = 0
    total_usd: Decimal = Decimal("0")
    any_problem: bool = False
    source_status: dict[str, str] = field(default_factory=dict)


# ── Step 2: collect holdings with per-source isolation ───────────────────────


def collect_holdings(settings: config.Config) -> tuple[list[Holding], dict[str, str]]:
    from sources.alpaca_source import build_alpaca_source
    from sources.evm_source import build_evm_sources

    sources: list[Any] = []
    alpaca = build_alpaca_source(settings)
    if alpaca is not None:
        sources.append(alpaca)
    sources.extend(build_evm_sources(settings))

    holdings: list[Holding] = []
    status: dict[str, str] = {}
    for src in sources:
        try:
            fetched = src.fetch_holdings()
            holdings.extend(fetched)
            status[src.key] = "ok" if fetched else "empty"
        except Exception as exc:  # isolation: one bad source never aborts the run
            status[src.key] = f"failed: {exc}"
            log.exception("source %s failed — continuing", getattr(src, "key", "?"))
    return holdings, status


# ── Step 3: resolve instruments + price crypto ───────────────────────────────


def resolve_instruments(conn, holdings: list[Holding]) -> dict[int, int]:
    """Map each holding (by id()) to an instrument_id via get_or_create."""
    mapping: dict[int, int] = {}
    for h in holdings:
        mapping[id(h)] = db.get_or_create_instrument(
            conn,
            asset_class=h.asset_class,
            symbol=h.symbol,
            chain=h.chain,
            address=h.address,
            decimals=h.decimals,
            coingecko_id=h.coingecko_id,
            is_stablecoin=h.is_stablecoin,
            display_name=h.display_name,
        )
    return mapping


def price_crypto(holdings: list[Holding], settings: config.Config) -> None:
    """Fill price fields for crypto holdings that arrived unpriced.

    Routing: native/listed-by-id (e.g. ETH) → /simple/price; ERC-20 → price by
    contract on Base. LP tokens → `unpriced` (labeled). Listed-but-not-found
    ERC-20 → `stale_unlisted`. Equities/cash are already priced and skipped.
    """
    from pricing.coingecko import CoinGeckoPricer

    pending = [h for h in holdings if h.price_status is None]
    if not pending:
        return

    pricer = CoinGeckoPricer(settings.coingecko_api_key, settings.coingecko_pro)

    id_wanted = {h.coingecko_id for h in pending
                 if h.coingecko_id and (not h.address or h.address == SENTINEL)}
    contract_wanted = {h.address for h in pending
                       if h.address and h.address != SENTINEL}

    by_id = pricer.price_ids(id_wanted) if id_wanted else {}
    by_contract = pricer.price_contracts(contract_wanted) if contract_wanted else {}

    for h in pending:
        if h.asset_class == "crypto_lp":
            h.price_status = config.PRICE_UNPRICED  # LP — Phase 1, labeled
            continue
        pp = None
        if h.coingecko_id and (not h.address or h.address == SENTINEL):
            pp = by_id.get(h.coingecko_id)
        elif h.address:
            pp = by_contract.get(h.address)
        if pp is not None:
            h.price_usd = pp.price_usd
            h.price_as_of = pp.as_of
            h.price_status = config.PRICE_LIVE
        else:
            # Known token but no live quote available.
            h.price_status = config.PRICE_STALE_UNLISTED


def _value(h: Holding) -> Decimal | None:
    if h.price_usd is None:
        return None
    return (h.quantity * h.price_usd)


# ── Step 4/5: persist holdings, prices, rollup ───────────────────────────────


def write_holdings(conn, holdings, mapping, snapshot_ts) -> int:
    rows = []
    for h in holdings:
        rows.append({
            "snapshot_ts": snapshot_ts,
            "source": h.source,
            "instrument_id": mapping[id(h)],
            "quantity": h.quantity,
            "raw_quantity": h.raw_quantity,
            "price_usd": h.price_usd,
            "value_usd": _value(h),
            "price_as_of": h.price_as_of,
            "price_status": h.price_status or config.PRICE_UNPRICED,
            "metadata": h.metadata,
        })
    return db.insert_holdings(conn, rows)


def write_tracked_prices(conn, holdings, mapping, snapshot_ts, settings) -> int:
    """Write one price row per tracked instrument (held ∪ watchlist)."""
    # Held instruments: take price straight from the holding.
    price_by_instrument: dict[int, tuple[Decimal | None, str]] = {}
    for h in holdings:
        iid = mapping[id(h)]
        status = h.price_status or config.PRICE_UNPRICED
        if iid not in price_by_instrument or price_by_instrument[iid][0] is None:
            price_by_instrument[iid] = (h.price_usd, status)

    # Watchlist-only instruments (not held this run): price them too.
    watchlist = set(db.get_watchlist_instrument_ids(conn))
    missing = watchlist - set(price_by_instrument)
    if missing:
        _price_watchlist_only(conn, missing, price_by_instrument, settings)

    rows = [
        {"instrument_id": iid, "ts": snapshot_ts,
         "price_usd": price, "price_status": status}
        for iid, (price, status) in price_by_instrument.items()
    ]
    return db.insert_prices(conn, rows)


def _price_watchlist_only(conn, instrument_ids, price_by_instrument, settings) -> None:
    from pricing.coingecko import CoinGeckoPricer
    from sources.alpaca_source import build_alpaca_source

    instruments = db.get_instruments(conn, list(instrument_ids))
    pricer = CoinGeckoPricer(settings.coingecko_api_key, settings.coingecko_pro)

    contract_addrs = [i.address for i in instruments
                      if i.address and i.address != SENTINEL]
    eth_ids = [i.coingecko_id for i in instruments
               if i.coingecko_id and (not i.address or i.address == SENTINEL)]
    equities = [i for i in instruments if i.asset_class in ("equity", "etf")]

    by_contract = pricer.price_contracts(contract_addrs) if contract_addrs else {}
    by_id = pricer.price_ids(eth_ids) if eth_ids else {}

    eq_prices: dict[str, tuple[Decimal, str]] = {}
    alpaca = build_alpaca_source(settings)
    if alpaca and equities:
        eq_prices = alpaca.latest_prices([i.symbol for i in equities])

    for inst in instruments:
        price: Decimal | None = None
        status = config.PRICE_STALE_UNLISTED
        if inst.asset_class in ("equity", "etf"):
            hit = eq_prices.get(inst.symbol)
            if hit:
                price, status = hit
            else:
                status = config.PRICE_UNPRICED
        elif inst.coingecko_id and (not inst.address or inst.address == SENTINEL):
            pp = by_id.get(inst.coingecko_id)
            if pp:
                price, status = pp.price_usd, config.PRICE_LIVE
        elif inst.address:
            pp = by_contract.get(inst.address)
            if pp:
                price, status = pp.price_usd, config.PRICE_LIVE
        price_by_instrument[inst.instrument_id] = (price, status)


def compute_rollup(conn, holdings, mapping, snapshot_ts) -> tuple[Decimal, bool]:
    total = Decimal("0")
    by_source: dict[str, Decimal] = {}
    by_asset: dict[str, Decimal] = {}
    any_problem = False
    for h in holdings:
        if (h.price_status or config.PRICE_UNPRICED) in config.PROBLEM_STATUSES:
            any_problem = True
        v = _value(h)
        if v is None:
            continue
        total += v
        by_source[h.source] = by_source.get(h.source, Decimal("0")) + v
        by_asset[h.asset_class] = by_asset.get(h.asset_class, Decimal("0")) + v
    db.insert_net_worth(
        conn,
        snapshot_ts=snapshot_ts,
        total_usd=total,
        by_source={k: str(v) for k, v in by_source.items()},
        by_asset_class={k: str(v) for k, v in by_asset.items()},
        any_problem=any_problem,
    )
    return total, any_problem


# ── Orchestration ────────────────────────────────────────────────────────────


def run(settings: config.Config | None = None) -> RunResult:
    settings = settings or config.settings
    for warning in settings.validate():
        log.warning(warning)

    snapshot_ts = now_utc()
    result = RunResult(snapshot_ts=snapshot_ts)

    holdings, source_status = collect_holdings(settings)
    result.source_status = source_status

    with db.connection() as conn:
        db.seed_instruments(conn)  # cheap, idempotent — guarantees day-one pricing
        mapping = resolve_instruments(conn, holdings)
        price_crypto(holdings, settings)

        result.holdings_written = write_holdings(conn, holdings, mapping, snapshot_ts)
        result.prices_written = write_tracked_prices(
            conn, holdings, mapping, snapshot_ts, settings
        )
        total, any_problem = compute_rollup(conn, holdings, mapping, snapshot_ts)
        result.total_usd = total
        result.any_problem = any_problem

        # D6 — alerts (targets + net-worth threshold). Imported lazily so the
        # orchestrator stays importable even mid-build.
        try:
            from targets import evaluate_targets
            from alerts.networth import evaluate_networth_alert

            evaluate_targets(conn, settings)
            evaluate_networth_alert(conn, settings, snapshot_ts, total, any_problem)
        except ImportError:
            log.debug("alerts module not present yet — skipping (pre-D6)")

    # D7 — OHLC maintenance (separate connection; best-effort, never fails run).
    try:
        from pricing.ohlc import maintain_ohlc

        maintain_ohlc(settings)
    except ImportError:
        log.debug("ohlc module not present yet — skipping (pre-D7)")
    except Exception:
        log.exception("ohlc maintenance failed — continuing")

    log.info(
        "snapshot %s | sources=%s | holdings=%d prices=%d total=$%.2f problem=%s",
        snapshot_ts.isoformat(), source_status, result.holdings_written,
        result.prices_written, float(result.total_usd), result.any_problem,
    )
    return result


def main() -> int:
    from obs import setup_logging

    setup_logging()
    try:
        run()
        return 0
    except config.ConfigError as exc:
        log.error("configuration error: %s", exc)
        return 2
    except Exception:
        log.exception("ingest run failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
