"""Shared types for holdings sources.

A `Source` reads balances from one place (a broker account, a wallet) and
returns a list of `Holding`s. Sources are read-only by contract — they never
import order/transfer APIs. The orchestrator prices and persists what they
return; sources do not touch the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


@dataclass
class Holding:
    """One position from one source at fetch time.

    `quantity` is the human-readable amount (decimals applied). `raw_quantity`
    is the precision-safe integer for crypto (None for equities).

    Pricing: a source that already knows the USD price (Alpaca returns last
    trade/close with its positions) sets `price_usd`/`price_as_of`/
    `price_status` directly. Crypto sources leave `price_status = None`, which
    signals the orchestrator to price the holding via CoinGecko.
    """

    source: str
    asset_class: str           # 'equity'|'etf'|'crypto_spot'|'crypto_lp'|'cash'
    symbol: str
    quantity: Decimal
    chain: str | None = None
    address: str | None = None         # contract addr / native sentinel (crypto)
    decimals: int | None = None
    raw_quantity: int | None = None    # raw integer (crypto); None for equities
    coingecko_id: str | None = None
    is_stablecoin: bool = False
    display_name: str | None = None
    price_usd: Decimal | None = None
    price_as_of: datetime | None = None
    price_status: str | None = None    # None => needs pricing by orchestrator
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(
        cls,
        *,
        source: str,
        asset_class: str,
        symbol: str,
        raw_quantity: int,
        decimals: int,
        chain: str | None = None,
        address: str | None = None,
        coingecko_id: str | None = None,
        is_stablecoin: bool = False,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Holding":
        """Build a crypto holding from a raw integer balance + token decimals.

        Quantity is computed exactly via Decimal scaling so no precision is lost.
        """
        qty = Decimal(raw_quantity) / (Decimal(10) ** decimals)
        return cls(
            source=source,
            asset_class=asset_class,
            symbol=symbol,
            quantity=qty,
            chain=chain,
            address=address.lower() if address else None,
            decimals=decimals,
            raw_quantity=raw_quantity,
            coingecko_id=coingecko_id,
            is_stablecoin=is_stablecoin,
            display_name=display_name,
            metadata=metadata or {},
        )


@runtime_checkable
class Source(Protocol):
    """Read-only holdings provider."""

    key: str

    def fetch_holdings(self) -> list[Holding]:
        """Return current holdings. Must raise on hard failure; the orchestrator
        isolates per-source errors so one bad source never aborts the run."""
        ...
