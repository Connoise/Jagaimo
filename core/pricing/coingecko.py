"""CoinGecko USD pricing for crypto.

Decision §2.1: ERC-20s are priced by **contract address** on Base
(`/simple/token_price/base`); native ETH and major coins by **id**
(`/simple/price`). `coingecko_id` is metadata only.

Decision §2.9: stablecoins are priced **live**, never pinned to $1 — a depeg
must be visible. `is_stablecoin` only affects display grouping downstream.

A pricer instance caches within a single run so repeated lookups (and the
held ∪ watchlist overlap) stay well under free-tier limits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable

import requests

import config

log = logging.getLogger("jagaimo.coingecko")

FREE_BASE = "https://api.coingecko.com/api/v3"
PRO_BASE = "https://pro-api.coingecko.com/api/v3"
BASE_PLATFORM = "base"  # CoinGecko asset-platform id for Base mainnet

# An HTTP getter maps (path, params) -> decoded JSON. Injectable for tests.
HttpGetter = Callable[[str, dict[str, Any]], Any]


@dataclass(frozen=True)
class PricePoint:
    price_usd: Decimal
    as_of: datetime
    status: str = config.PRICE_LIVE


def _to_decimal(value: Any) -> Decimal:
    # Route through str to avoid binary float artifacts.
    return Decimal(str(value))


def _as_of(unix_ts: Any) -> datetime:
    if unix_ts is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc)


class CoinGeckoPricer:
    """Live USD pricing with a per-instance (per-run) cache."""

    def __init__(
        self,
        api_key: str | None = None,
        pro: bool = False,
        *,
        http: HttpGetter | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key
        self.pro = pro
        self.timeout = timeout
        self._http = http or self._requests_get
        self._session = requests.Session()
        self._contract_cache: dict[str, PricePoint] = {}
        self._id_cache: dict[str, PricePoint] = {}

    @property
    def base_url(self) -> str:
        return PRO_BASE if self.pro else FREE_BASE

    def _requests_get(self, path: str, params: dict[str, Any]) -> Any:
        headers = {}
        if self.api_key:
            header = "x-cg-pro-api-key" if self.pro else "x-cg-demo-api-key"
            headers[header] = self.api_key
        resp = self._session.get(
            f"{self.base_url}{path}", params=params, headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Pricing by contract (ERC-20 on Base) ──
    def price_contracts(self, addresses: Iterable[str]) -> dict[str, PricePoint]:
        """Return {lowercased_address: PricePoint} for the addresses found.

        Missing addresses are simply absent from the result (the caller decides
        whether that means `stale_unlisted` or `unpriced`). Cached per run.
        """
        wanted = [a.lower() for a in addresses]
        out: dict[str, PricePoint] = {}
        to_fetch = []
        for a in wanted:
            if a in self._contract_cache:
                out[a] = self._contract_cache[a]
            else:
                to_fetch.append(a)
        if to_fetch:
            data = self._http(
                f"/simple/token_price/{BASE_PLATFORM}",
                {
                    "contract_addresses": ",".join(to_fetch),
                    "vs_currencies": "usd",
                    "include_last_updated_at": "true",
                },
            ) or {}
            for addr, payload in data.items():
                if "usd" not in payload:
                    continue
                pp = PricePoint(
                    price_usd=_to_decimal(payload["usd"]),
                    as_of=_as_of(payload.get("last_updated_at")),
                )
                self._contract_cache[addr.lower()] = pp
                out[addr.lower()] = pp
        return out

    # ── Pricing by id (native ETH / major coins) ──
    def price_ids(self, ids: Iterable[str]) -> dict[str, PricePoint]:
        wanted = [i for i in ids if i]
        out: dict[str, PricePoint] = {}
        to_fetch = []
        for i in wanted:
            if i in self._id_cache:
                out[i] = self._id_cache[i]
            else:
                to_fetch.append(i)
        if to_fetch:
            data = self._http(
                "/simple/price",
                {
                    "ids": ",".join(sorted(set(to_fetch))),
                    "vs_currencies": "usd",
                    "include_last_updated_at": "true",
                },
            ) or {}
            for cid, payload in data.items():
                if "usd" not in payload:
                    continue
                pp = PricePoint(
                    price_usd=_to_decimal(payload["usd"]),
                    as_of=_as_of(payload.get("last_updated_at")),
                )
                self._id_cache[cid] = pp
                out[cid] = pp
        return out
