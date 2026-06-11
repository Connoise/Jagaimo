"""Coinbase source — read-only custodial balances + historical fills.

Talks to the Coinbase Advanced Trade API with a CDP key (the **View**
permission is sufficient — create the key read-only). Only `get_accounts` and
`get_fills` are ever called; no order or transfer endpoint is imported
anywhere (grep-verifiable, plan §10).

Balances are custodial — there is no contract address — so instruments are
identified by bare symbol (chain/address NULL) and priced by CoinGecko **id**
via the COINBASE_COINGECKO_IDS map (env-extendable). An unmapped symbol is
recorded and shows as `stale_unlisted` until mapped; it never fails the run.

Fills feed the trade ledger (`tracking.transactions`): every fill has a
globally unique trade id, which is the dedup key, so incremental re-fetches
are idempotent. Fills cover Advanced Trade executions; conversions, staking
rewards, and transfers are not fills and are out of scope for the ledger.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

import config
from sources.base import Holding

log = logging.getLogger("jagaimo.coinbase")

# Fiat currencies valued 1:1 as cash. Non-USD fiat is skipped (USD tracker).
_CASH_CURRENCIES = {"USD"}

_PAGE_LIMIT = 250


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from an SDK response object or a plain dict (tests)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class CoinbaseSource:
    """Read-only Coinbase account balances (+ fills for the ledger)."""

    key = config.SOURCE_COINBASE

    def __init__(
        self,
        key_file: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        *,
        client=None,
        settings: config.Config | None = None,
    ) -> None:
        s = settings or config.settings
        self.settings = s
        self.key_file = key_file or s.coinbase_key_file
        self.api_key = api_key or s.coinbase_api_key_name
        self.api_secret = api_secret or s.coinbase_api_private_key
        self._client = client  # injectable for tests

    def _client_or_none(self):
        if self._client is not None:
            return self._client
        try:
            from coinbase.rest import RESTClient
        except ImportError:
            log.warning("coinbase-advanced-py not installed — Coinbase skipped")
            return None
        if self.key_file:
            self._client = RESTClient(key_file=self.key_file)
        elif self.api_key and self.api_secret:
            self._client = RESTClient(api_key=self.api_key, api_secret=self.api_secret)
        else:
            return None
        return self._client

    # ── balances ──
    def _accounts(self, client) -> Iterator[Any]:
        cursor: str | None = None
        while True:
            resp = client.get_accounts(limit=_PAGE_LIMIT, cursor=cursor)
            for account in _field(resp, "accounts", []) or []:
                yield account
            if not _field(resp, "has_next"):
                return
            cursor = _field(resp, "cursor")
            if not cursor:
                return

    def fetch_holdings(self) -> list[Holding]:
        client = self._client_or_none()
        if client is None:
            log.info("coinbase disabled (no key) — skipping")
            return []

        as_of = datetime.now(timezone.utc)
        holdings: list[Holding] = []
        for account in self._accounts(client):
            currency = (_field(account, "currency") or "").upper()
            available = _dec(_field(_field(account, "available_balance"), "value"))
            hold = _dec(_field(_field(account, "hold"), "value"))
            quantity = (available or Decimal("0")) + (hold or Decimal("0"))
            if not currency or quantity == 0:
                continue

            meta = {
                "account_uuid": _field(account, "uuid"),
                "available": str(available or 0),
                "hold": str(hold or 0),
            }
            if currency in _CASH_CURRENCIES:
                holdings.append(
                    Holding(
                        source=self.key,
                        asset_class="cash",
                        symbol="USD",
                        quantity=quantity,
                        display_name="US Dollar (Coinbase cash)",
                        price_usd=Decimal("1"),
                        price_as_of=as_of,
                        price_status=config.PRICE_LIVE,
                        metadata={**meta, "kind": "cash"},
                    )
                )
                continue
            coingecko_id = self.settings.coinbase_coingecko_id(currency)
            if coingecko_id is None:
                log.warning(
                    "coinbase: no CoinGecko id for %s — recorded unpriced "
                    "(map it via COINBASE_COINGECKO_IDS)", currency,
                )
            holdings.append(
                Holding(
                    source=self.key,
                    asset_class="crypto_spot",
                    symbol=currency,
                    quantity=quantity,
                    coingecko_id=coingecko_id,
                    is_stablecoin=currency in config.STABLECOIN_SYMBOLS,
                    display_name=_field(account, "name"),
                    # price_status None → the orchestrator prices by id.
                    metadata=meta,
                )
            )
        log.info("coinbase: %d holdings", len(holdings))
        return holdings

    # ── fills → ledger rows ──
    def fetch_fills(self, since: datetime | None = None) -> list[dict]:
        """Fills as `tracking.transactions` row dicts (without instrument_id).

        `since` bounds the fetch for incremental syncs; dedup by trade id makes
        overlap harmless. Never raises on a malformed fill — it is skipped.
        """
        client = self._client_or_none()
        if client is None:
            return []

        rows: list[dict] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"limit": _PAGE_LIMIT}
            if cursor:
                kwargs["cursor"] = cursor
            if since is not None:
                kwargs["start_sequence_timestamp"] = (
                    since.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                )
            resp = client.get_fills(**kwargs)
            fills = _field(resp, "fills", []) or []
            for fill in fills:
                row = self._fill_to_row(fill)
                if row is not None:
                    rows.append(row)
            cursor = _field(resp, "cursor")
            if not cursor or not fills:
                break
        return rows

    @staticmethod
    def _fill_to_row(fill: Any) -> dict | None:
        trade_id = _field(fill, "trade_id")
        product_id = _field(fill, "product_id") or ""
        trade_ts = _parse_ts(_field(fill, "trade_time"))
        side_raw = (_field(fill, "side") or "").upper()
        if not trade_id or not product_id or trade_ts is None:
            return None

        base_symbol, _, quote = product_id.partition("-")
        price = _dec(_field(fill, "price"))
        size = _dec(_field(fill, "size"))
        # size_in_quote=True means `size` is denominated in the quote currency.
        size_in_quote = bool(_field(fill, "size_in_quote"))
        quantity = size
        gross = None  # in quote currency
        if size is not None:
            if size_in_quote:
                gross = size
                quantity = size / price if price else None
            elif price is not None:
                gross = size * price

        usd_quote = quote in {"USD", "USDC"}
        fees = _dec(_field(fill, "commission")) if usd_quote else None
        amount = None
        if usd_quote and gross is not None:
            # Signed net cash flow: buys consume cash (negative), sells add.
            if side_raw == "BUY":
                amount = -(gross + (fees or Decimal("0")))
            else:
                amount = gross - (fees or Decimal("0"))

        return {
            "source": config.SOURCE_COINBASE,
            "account": _field(fill, "retail_portfolio_id"),
            "instrument_id": None,  # resolved by the ledger importer
            "symbol": base_symbol.upper(),
            "trade_ts": trade_ts,
            "settlement_ts": None,
            "side": "buy" if side_raw == "BUY" else "sell",
            "kind": "fill",
            "quantity": quantity,
            "price_usd": price if usd_quote else None,
            "fees_usd": fees,
            "amount_usd": amount,
            "description": f"{side_raw or '?'} {product_id}",
            "natural_key": f"cb:{trade_id}",
        }


def build_coinbase_source(
    settings: config.Config | None = None,
) -> CoinbaseSource | None:
    settings = settings or config.settings
    if not settings.coinbase_enabled:
        return None
    return CoinbaseSource(settings=settings)
