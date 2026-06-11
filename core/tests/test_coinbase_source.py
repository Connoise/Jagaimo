"""Offline tests for the Coinbase source (fake client; SDK never imported)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import config
from sources.coinbase_source import CoinbaseSource, build_coinbase_source


def _cfg(**overrides) -> config.Config:
    base = dict(
        database_url="postgres://x",
        alpaca_api_key_id=None,
        alpaca_api_secret_key=None,
        alpaca_base_url="x",
        alchemy_api_key=None,
        base_rpc_url=None,
    )
    base.update(overrides)
    return config.Config(**base)


def _account(currency, available, hold="0", uuid="u1", name=None):
    return {
        "uuid": uuid,
        "name": name or f"{currency} Wallet",
        "currency": currency,
        "available_balance": {"value": available, "currency": currency},
        "hold": {"value": hold, "currency": currency},
    }


class FakeClient:
    """Two-page accounts response + canned fills, dict-shaped like the SDK."""

    def __init__(self, accounts=(), fills=()):
        self._accounts = list(accounts)
        self._fills = list(fills)
        self.fill_kwargs: list[dict] = []

    def get_accounts(self, limit=250, cursor=None):
        if cursor is None and len(self._accounts) > 1:
            return {"accounts": self._accounts[:1], "has_next": True,
                    "cursor": "page2"}
        rest = self._accounts[1:] if cursor == "page2" else self._accounts
        return {"accounts": rest, "has_next": False, "cursor": ""}

    def get_fills(self, **kwargs):
        self.fill_kwargs.append(kwargs)
        return {"fills": self._fills, "cursor": ""}


# ── enablement ───────────────────────────────────────────────────────────────


def test_build_disabled_without_keys():
    assert build_coinbase_source(_cfg()) is None


def test_build_enabled_with_key_pair():
    cfg = _cfg(coinbase_api_key_name="organizations/x/apiKeys/y",
               coinbase_api_private_key="-----BEGIN EC PRIVATE KEY-----\n...")
    assert build_coinbase_source(cfg) is not None


def test_no_client_degrades_empty():
    src = CoinbaseSource(settings=_cfg())
    assert src.fetch_holdings() == []
    assert src.fetch_fills() == []


# ── balances ─────────────────────────────────────────────────────────────────


def test_fetch_holdings_paginated_and_classified():
    client = FakeClient(accounts=[
        _account("BTC", "0.5", hold="0.1", uuid="u-btc"),
        _account("USD", "1000.00", uuid="u-usd"),
        _account("ZZZNEW", "42", uuid="u-zzz"),     # unmapped symbol
        _account("ETH", "0", uuid="u-eth"),          # zero balance → skipped
    ])
    holdings = CoinbaseSource(settings=_cfg(), client=client).fetch_holdings()
    by_symbol = {h.symbol: h for h in holdings}

    assert set(by_symbol) == {"BTC", "USD", "ZZZNEW"}

    btc = by_symbol["BTC"]
    assert btc.quantity == Decimal("0.6")            # available + hold
    assert btc.asset_class == "crypto_spot"
    assert btc.coingecko_id == "bitcoin"             # built-in id map
    assert btc.chain is None and btc.address is None  # custodial, not on-chain
    assert btc.price_status is None                  # orchestrator prices by id

    usd = by_symbol["USD"]
    assert usd.asset_class == "cash"
    assert usd.price_usd == Decimal("1")
    assert usd.price_status == config.PRICE_LIVE

    assert by_symbol["ZZZNEW"].coingecko_id is None  # recorded, not failed


def test_coingecko_id_env_override():
    cfg = _cfg(coinbase_coingecko_overrides={"ZZZNEW": "zzz-token"})
    client = FakeClient(accounts=[_account("ZZZNEW", "1")])
    holdings = CoinbaseSource(settings=cfg, client=client).fetch_holdings()
    assert holdings[0].coingecko_id == "zzz-token"


# ── fills → ledger rows ──────────────────────────────────────────────────────


def _fill(**overrides):
    fill = {
        "trade_id": "t-1",
        "product_id": "BTC-USD",
        "side": "BUY",
        "price": "50000",
        "size": "0.01",
        "size_in_quote": False,
        "commission": "2.50",
        "trade_time": "2025-06-01T12:00:00Z",
        "retail_portfolio_id": "pf-1",
    }
    fill.update(overrides)
    return fill


def test_fill_buy_mapping_and_sign():
    client = FakeClient(fills=[_fill()])
    rows = CoinbaseSource(settings=_cfg(), client=client).fetch_fills()
    assert len(rows) == 1
    r = rows[0]
    assert r["natural_key"] == "cb:t-1"              # trade id is the dedup key
    assert r["symbol"] == "BTC"
    assert r["side"] == "buy"
    assert r["quantity"] == Decimal("0.01")
    assert r["price_usd"] == Decimal("50000")
    assert r["fees_usd"] == Decimal("2.50")
    assert r["amount_usd"] == Decimal("-502.50")     # buy = cash out (signed)
    assert r["trade_ts"] == datetime(2025, 6, 1, 12, tzinfo=timezone.utc)


def test_fill_sell_and_size_in_quote():
    client = FakeClient(fills=[
        _fill(trade_id="t-2", side="SELL", size="500", size_in_quote=True,
              commission="1.00"),
    ])
    rows = CoinbaseSource(settings=_cfg(), client=client).fetch_fills()
    r = rows[0]
    assert r["side"] == "sell"
    assert r["quantity"] == Decimal("0.01")          # 500 quote / 50000 price
    assert r["amount_usd"] == Decimal("499.00")      # sell = cash in, net of fee
    assert r["fees_usd"] == Decimal("1.00")


def test_fill_non_usd_quote_has_no_usd_amount():
    client = FakeClient(fills=[_fill(trade_id="t-3", product_id="ETH-BTC")])
    rows = CoinbaseSource(settings=_cfg(), client=client).fetch_fills()
    r = rows[0]
    assert r["symbol"] == "ETH"
    assert r["price_usd"] is None
    assert r["amount_usd"] is None                   # honest: not a USD figure


def test_fill_since_passed_as_rfc3339():
    client = FakeClient(fills=[])
    since = datetime(2025, 5, 1, tzinfo=timezone.utc)
    CoinbaseSource(settings=_cfg(), client=client).fetch_fills(since)
    assert client.fill_kwargs[0]["start_sequence_timestamp"] == "2025-05-01T00:00:00Z"


def test_malformed_fill_skipped():
    client = FakeClient(fills=[_fill(trade_id=None)])
    assert CoinbaseSource(settings=_cfg(), client=client).fetch_fills() == []
