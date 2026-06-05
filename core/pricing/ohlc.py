"""OHLC backfill + maintenance for instrument candlesticks (milestone D7).

For every tracked instrument (held ∪ watchlist) keep `1h` and `1d` candles in
`tracking.ohlc_bars`:

  * equities / ETFs   → Alpaca historical bars,
  * native ETH / coins with a coingecko_id → CoinGecko `/coins/{id}/ohlc`,
  * Base ERC-20 tokens → GeckoTerminal OHLCV by token address.

On first sighting (no bars yet) we backfill a long window; thereafter we append
from the last stored bar forward. All upserts are idempotent, so re-running is
safe. OHLC maintenance is best-effort — a provider failure logs and is skipped;
it never aborts an ingest run (plan §8).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

import config
from db import client as db

log = logging.getLogger("jagaimo.ohlc")

TIMEFRAMES = ("1h", "1d")

# How far back to backfill on first sighting, per timeframe.
BACKFILL_DAYS = {"1d": 730, "1h": 30}


@dataclass(frozen=True)
class Bar:
    ts: datetime               # bar open, UTC
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None = None


# A fetcher: (key, timeframe, since) -> list[Bar]. `key` is a symbol (equities),
# a coingecko id, or a contract address depending on the route.
Fetcher = Callable[[str, str, datetime], list[Bar]]


@dataclass
class OhlcFetchers:
    equities: Fetcher
    by_id: Fetcher
    by_contract: Fetcher


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _D(v) -> Decimal | None:
    return None if v is None else Decimal(str(v))


# ── Default live fetchers (run on the host; best-effort, return [] on failure) ─


def fetch_equity_bars(symbol: str, timeframe: str, since: datetime) -> list[Bar]:
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        s = config.settings
        if not s.alpaca_enabled:
            return []
        client = StockHistoricalDataClient(s.alpaca_api_key_id, s.alpaca_api_secret_key)
        tf = TimeFrame.Hour if timeframe == "1h" else TimeFrame.Day
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=since)
        bars = client.get_stock_bars(req)
        return [
            Bar(b.timestamp, _D(b.open), _D(b.high), _D(b.low), _D(b.close),
                _D(b.volume))
            for b in bars.data.get(symbol, [])
        ]
    except Exception as exc:
        log.warning("equity OHLC %s/%s failed: %s", symbol, timeframe, exc)
        return []


def fetch_coingecko_ohlc(coingecko_id: str, timeframe: str, since: datetime) -> list[Bar]:
    try:
        import requests

        s = config.settings
        base = ("https://pro-api.coingecko.com/api/v3" if s.coingecko_pro
                else "https://api.coingecko.com/api/v3")
        days = max(1, (_now() - since).days or 1)
        headers = {}
        if s.coingecko_api_key:
            h = "x-cg-pro-api-key" if s.coingecko_pro else "x-cg-demo-api-key"
            headers[h] = s.coingecko_api_key
        resp = requests.get(
            f"{base}/coins/{coingecko_id}/ohlc",
            params={"vs_currency": "usd", "days": str(min(days, 365))},
            headers=headers, timeout=20,
        )
        resp.raise_for_status()
        # [[ts_ms, o, h, l, c], ...] — CoinGecko OHLC carries no volume.
        out = []
        for ts_ms, o, h, l, c in resp.json():
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            out.append(Bar(ts, _D(o), _D(h), _D(l), _D(c), None))
        return out
    except Exception as exc:
        log.warning("coingecko OHLC %s/%s failed: %s", coingecko_id, timeframe, exc)
        return []


def fetch_geckoterminal_ohlcv(address: str, timeframe: str, since: datetime) -> list[Bar]:
    try:
        import requests

        # GeckoTerminal: day | hour aggregation on Base.
        tf = "day" if timeframe == "1d" else "hour"
        url = (f"https://api.geckoterminal.com/api/v2/networks/base/tokens/"
               f"{address}/ohlcv/{tf}")
        resp = requests.get(url, params={"aggregate": "1", "limit": "1000"},
                            timeout=20)
        resp.raise_for_status()
        rows = resp.json().get("data", {}).get("attributes", {}).get("ohlcv_list", [])
        out = []
        for ts_s, o, h, l, c, v in rows:
            ts = datetime.fromtimestamp(ts_s, tz=timezone.utc)
            out.append(Bar(ts, _D(o), _D(h), _D(l), _D(c), _D(v)))
        return out
    except Exception as exc:
        log.warning("geckoterminal OHLC %s/%s failed: %s", address, timeframe, exc)
        return []


DEFAULT_FETCHERS = OhlcFetchers(
    equities=fetch_equity_bars,
    by_id=fetch_coingecko_ohlc,
    by_contract=fetch_geckoterminal_ohlcv,
)


# ── Routing + maintenance ────────────────────────────────────────────────────


def _route(inst: db.InstrumentRow) -> tuple[str, str] | None:
    """Return (fetcher_kind, key) for an instrument, or None if unsupported."""
    sentinel = config.NATIVE_ETH_SENTINEL.lower()
    if inst.asset_class in ("equity", "etf"):
        return ("equities", inst.symbol)
    if inst.coingecko_id and (not inst.address or inst.address == sentinel):
        return ("by_id", inst.coingecko_id)
    if inst.address and inst.address != sentinel:
        return ("by_contract", inst.address)
    if inst.coingecko_id:  # listed coin without a Base contract
        return ("by_id", inst.coingecko_id)
    return None


def maintain_instrument(
    conn, inst: db.InstrumentRow, fetchers: OhlcFetchers
) -> int:
    route = _route(inst)
    if route is None:
        log.debug("no OHLC route for instrument %s (%s)", inst.instrument_id,
                  inst.symbol)
        return 0
    kind, key = route
    fetcher: Fetcher = getattr(fetchers, kind)

    written = 0
    for tf in TIMEFRAMES:
        last = db.latest_ohlc_ts(conn, inst.instrument_id, tf)
        if last is None:
            since = _now() - timedelta(days=BACKFILL_DAYS[tf])
        else:
            since = last  # append from the last stored bar forward (idempotent)
        bars = fetcher(key, tf, since)
        rows = [
            {"instrument_id": inst.instrument_id, "timeframe": tf, "ts": b.ts,
             "open": b.open, "high": b.high, "low": b.low, "close": b.close,
             "volume": b.volume}
            for b in bars if b.ts >= since or last is None
        ]
        written += db.upsert_ohlc_bars(conn, rows)
    return written


def maintain_ohlc(
    settings: config.Config | None = None, *, fetchers: OhlcFetchers | None = None
) -> int:
    """Maintain OHLC for every tracked instrument. Returns total bars upserted."""
    settings = settings or config.settings
    fetchers = fetchers or DEFAULT_FETCHERS
    total = 0
    with db.connection() as conn:
        ids = db.get_tracked_instrument_ids(conn)
        instruments = db.get_instruments(conn, ids)
        for inst in instruments:
            try:
                total += maintain_instrument(conn, inst, fetchers)
            except Exception:
                log.exception("OHLC maintenance failed for %s", inst.symbol)
    log.info("ohlc maintenance: %d bars upserted across %d instruments",
             total, len(ids))
    return total
