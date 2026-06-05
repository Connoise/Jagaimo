"""Alpaca equities source — read-only positions + cash, valued at last trade/close.

Decision §2.7: Alpaca `/v2/clock` is the single source of truth for market
state. Open → equities are priced `live`; closed → `last_close` (a correct
value shown normally, NOT a problem).

Alpaca is OPTIONAL (§3): with no creds or an empty account, this source
contributes nothing and never errors — the tracker runs on wallets alone.

Strictly read-only: only account/positions/clock/market-data reads are used.
No order or trading-write API is imported anywhere (grep-verifiable, §10).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

import config
from sources.base import Holding

log = logging.getLogger("jagaimo.alpaca")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AlpacaSource:
    """Read-only equities/ETF positions + cash."""

    key = config.SOURCE_ALPACA

    def __init__(
        self,
        api_key_id: str | None = None,
        api_secret_key: str | None = None,
        base_url: str | None = None,
        *,
        trading_client=None,
    ) -> None:
        s = config.settings
        self.api_key_id = api_key_id or s.alpaca_api_key_id
        self.api_secret_key = api_secret_key or s.alpaca_api_secret_key
        self.base_url = base_url or s.alpaca_base_url
        self._client = trading_client  # injectable for tests
        self._market_open: bool | None = None

    # ── client construction ──
    @property
    def enabled(self) -> bool:
        return bool(self._client) or bool(self.api_key_id and self.api_secret_key)

    def _client_or_none(self):
        if self._client is not None:
            return self._client
        if not (self.api_key_id and self.api_secret_key):
            return None
        from alpaca.trading.client import TradingClient

        paper = "paper" in (self.base_url or "")
        self._client = TradingClient(
            self.api_key_id, self.api_secret_key, paper=paper
        )
        return self._client

    # ── market state ──
    def is_market_open(self) -> bool:
        if self._market_open is not None:
            return self._market_open
        client = self._client_or_none()
        if client is None:
            self._market_open = False
            return False
        try:
            self._market_open = bool(client.get_clock().is_open)
        except Exception as exc:  # treat unknown clock as closed (conservative)
            log.warning("alpaca clock read failed: %s", exc)
            self._market_open = False
        return self._market_open

    # ── holdings ──
    def fetch_holdings(self) -> list[Holding]:
        client = self._client_or_none()
        if client is None:
            log.info("alpaca disabled (no creds) — skipping equities")
            return []

        status = config.PRICE_LIVE if self.is_market_open() else config.PRICE_LAST_CLOSE
        as_of = _now()
        holdings: list[Holding] = []

        # Positions.
        try:
            positions = client.get_all_positions()
        except Exception as exc:
            log.warning("alpaca positions read failed: %s — degrading", exc)
            positions = []
        for p in positions:
            holding = self._position_to_holding(p, status, as_of)
            if holding is not None:
                holdings.append(holding)

        # Cash (USD), valued 1:1, always live.
        try:
            account = client.get_account()
            cash = Decimal(str(account.cash))
            if cash != 0:
                holdings.append(
                    Holding(
                        source=self.key,
                        asset_class="cash",
                        symbol="USD",
                        quantity=cash,
                        display_name="US Dollar (Alpaca cash)",
                        price_usd=Decimal("1"),
                        price_as_of=as_of,
                        price_status=config.PRICE_LIVE,
                        metadata={"kind": "cash"},
                    )
                )
        except Exception as exc:
            log.warning("alpaca account/cash read failed: %s", exc)

        log.info("alpaca: %d holdings (market_open=%s)", len(holdings),
                 self._market_open)
        return holdings

    @staticmethod
    def _position_to_holding(p, status: str, as_of: datetime) -> Holding | None:
        try:
            qty = Decimal(str(p.qty))
            if qty == 0:
                return None
            price = Decimal(str(p.current_price)) if p.current_price else None
            asset_class = "etf" if _looks_like_etf(p) else "equity"
            return Holding(
                source=config.SOURCE_ALPACA,
                asset_class=asset_class,
                symbol=str(p.symbol),
                quantity=qty,
                price_usd=price,
                price_as_of=as_of,
                price_status=status if price is not None else config.PRICE_UNPRICED,
                metadata={"market_value": str(getattr(p, "market_value", "") or "")},
            )
        except Exception as exc:
            log.warning("alpaca position parse failed for %s: %s",
                        getattr(p, "symbol", "?"), exc)
            return None

    def latest_prices(self, symbols: list[str]) -> dict[str, tuple[Decimal, str]]:
        """Best-effort last trade for watchlisted equities not currently held.

        Returns {symbol: (price, status)}. Missing/failed symbols are omitted;
        the orchestrator marks those `unpriced`. Uses the historical-data client
        (read-only). Never raises.
        """
        if not symbols:
            return {}
        client = self._client_or_none()
        if client is None:
            return {}
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockLatestTradeRequest

            data = StockHistoricalDataClient(self.api_key_id, self.api_secret_key)
            req = StockLatestTradeRequest(symbol_or_symbols=symbols)
            trades = data.get_stock_latest_trade(req)
            status = (config.PRICE_LIVE if self.is_market_open()
                      else config.PRICE_LAST_CLOSE)
            return {
                sym: (Decimal(str(t.price)), status)
                for sym, t in trades.items() if t and t.price
            }
        except Exception as exc:
            log.warning("alpaca latest_prices failed: %s", exc)
            return {}


def _looks_like_etf(position) -> bool:
    """Alpaca positions don't reliably flag ETFs; default everything to equity
    unless the asset_class explicitly says otherwise."""
    ac = getattr(position, "asset_class", None)
    return str(ac).lower().endswith("etf") if ac is not None else False


def build_alpaca_source(settings: config.Config | None = None) -> AlpacaSource | None:
    settings = settings or config.settings
    if not settings.alpaca_enabled:
        return None
    return AlpacaSource()
