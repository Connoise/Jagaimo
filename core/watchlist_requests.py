"""Resolve browser-submitted watchlist requests into real instruments.

The viewer can only write the user-config tables (RLS), so "add a new stock or
token to track" is enqueued in `tracking.watchlist_requests`. Each ingest run
this module drains the queue: validate the input, get_or_create the instrument,
add it to the watchlist (so it is priced from the next snapshot on), and mark
the request resolved (or error, with a message the UI can show).

Per-request isolation: one bad request is marked `error` and never aborts the
rest of the run.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

import config
from db import client as db

log = logging.getLogger("jagaimo.requests")

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")

# Enrich a token address -> metadata dict ({symbol, decimals, name}) or None.
TokenEnricher = Callable[[str], dict | None]


def normalize_equity_symbol(symbol: str | None) -> str:
    """Validate + normalize an equity ticker, or raise ValueError."""
    if not symbol or not symbol.strip():
        raise ValueError("A ticker symbol is required for a stock.")
    s = symbol.strip().upper()
    if not _SYMBOL_RE.match(s):
        raise ValueError(f"Invalid ticker {symbol!r}.")
    return s


def normalize_token_address(address: str | None) -> str:
    """Validate + lowercase a token contract address, or raise ValueError."""
    if not address or not address.strip():
        raise ValueError("A contract address is required for a token.")
    a = address.strip().lower()
    if not _ADDRESS_RE.match(a):
        raise ValueError(f"Invalid contract address {address!r} (expected 0x + 40 hex).")
    return a


def _default_enricher(settings: config.Config) -> TokenEnricher:
    """Best-effort token metadata via Alchemy, if configured; else a no-op."""
    if not settings.use_alchemy:
        return lambda _addr: None

    def enrich(address: str) -> dict | None:
        try:
            from sources.evm_source import EvmSource

            src = EvmSource("enrich", address, alchemy_api_key=settings.alchemy_api_key)
            return src._alchemy_rpc("alchemy_getTokenMetadata", [address])
        except Exception as exc:  # never fail a request on enrichment
            log.warning("token metadata enrichment failed for %s: %s", address, exc)
            return None

    return enrich


def _resolve_token(conn, req, settings, enrich: TokenEnricher) -> int:
    address = normalize_token_address(req.address)
    chain = (req.chain or config.BASE_CHAIN).strip().lower()

    symbol = (req.symbol or "").strip()
    decimals: int | None = None
    display_name: str | None = None

    meta = enrich(address)
    if meta:
        symbol = symbol or (meta.get("symbol") or "").strip()
        if meta.get("decimals") is not None:
            decimals = int(meta["decimals"])
        display_name = meta.get("name")

    if not symbol:
        symbol = f"{address[:6]}…{address[-4:]}"  # legible fallback

    instrument_id = db.get_or_create_instrument(
        conn,
        asset_class="crypto_spot",
        symbol=symbol,
        chain=chain,
        address=address,
        decimals=decimals,
        is_stablecoin=symbol.upper() in config.STABLECOIN_SYMBOLS,
        display_name=display_name,
    )
    db.add_to_watchlist(conn, instrument_id, req.note)
    return instrument_id


def _resolve_equity(conn, req) -> int:
    symbol = normalize_equity_symbol(req.symbol)
    instrument_id = db.get_or_create_instrument(
        conn, asset_class="equity", symbol=symbol
    )
    db.add_to_watchlist(conn, instrument_id, req.note)
    return instrument_id


def process_watchlist_requests(
    conn, settings: config.Config, *, enrich: TokenEnricher | None = None
) -> int:
    """Drain pending requests. Returns the number resolved successfully."""
    pending = db.get_pending_watchlist_requests(conn)
    if not pending:
        return 0
    enrich = enrich or _default_enricher(settings)

    resolved = 0
    for req in pending:
        try:
            if req.kind == "token":
                iid = _resolve_token(conn, req, settings, enrich)
            elif req.kind == "equity":
                iid = _resolve_equity(conn, req)
            else:
                raise ValueError(f"unknown request kind {req.kind!r}")
            db.resolve_watchlist_request(
                conn, req.request_id, status="resolved", instrument_id=iid,
                detail="added to watchlist",
            )
            resolved += 1
            log.info("watchlist request %s resolved -> instrument %s",
                     req.request_id, iid)
        except Exception as exc:
            db.resolve_watchlist_request(
                conn, req.request_id, status="error", detail=str(exc)
            )
            log.warning("watchlist request %s failed: %s", req.request_id, exc)
    return resolved
