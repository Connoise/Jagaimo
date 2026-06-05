"""Offline smoke/unit tests for the Jagaimo core.

These exercise the pure logic (no network) plus a couple of DB-gated checks via
the `db_conn` fixture. Run: `cd core && .venv/bin/pytest -q`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

import config


# ── config ───────────────────────────────────────────────────────────────────


def test_seed_instruments_present():
    syms = {s.symbol for s in config.SEED_INSTRUMENTS}
    assert {"ETH", "WETH", "USDC", "AERO"} <= syms
    usdc = next(s for s in config.SEED_INSTRUMENTS if s.symbol == "USDC")
    assert usdc.is_stablecoin and usdc.decimals == 6


def test_validate_requires_database_url():
    cfg = config.Config(database_url=None, alpaca_api_key_id=None,
                        alpaca_api_secret_key=None, alpaca_base_url="x",
                        alchemy_api_key=None, base_rpc_url=None)
    with pytest.raises(config.ConfigError):
        cfg.validate()


def test_validate_requires_a_source():
    cfg = config.Config(database_url="postgres://x", alpaca_api_key_id=None,
                        alpaca_api_secret_key=None, alpaca_base_url="x",
                        alchemy_api_key=None, base_rpc_url=None)
    with pytest.raises(config.ConfigError):
        cfg.validate()


def test_evm_toggle_and_wallets():
    cfg = config.Config(database_url="postgres://x", alpaca_api_key_id=None,
                        alpaca_api_secret_key=None, alpaca_base_url="x",
                        alchemy_api_key="k", base_rpc_url=None,
                        wallet_01_address="0xabc")
    assert cfg.evm_enabled and cfg.use_alchemy
    assert cfg.wallets == [(config.SOURCE_WALLET_01, "0xabc")]
    assert cfg.validate()  # returns warnings list, does not raise


# ── Holding / EVM parsing ────────────────────────────────────────────────────


def test_holding_from_raw_precision():
    from sources.base import Holding

    h = Holding.from_raw(source="w", asset_class="crypto_spot", symbol="USDC",
                         raw_quantity=123_456_789, decimals=6)
    assert h.quantity == Decimal("123.456789")
    assert h.raw_quantity == 123_456_789


def test_evm_hex_and_spam():
    from sources.evm_source import hex_to_int, is_probable_spam

    assert hex_to_int("0x") == 0
    assert hex_to_int(None) == 0
    assert hex_to_int(hex(10**18)) == 10**18
    assert is_probable_spam({"symbol": "USDC", "decimals": 6, "name": "USD Coin"}) is False
    assert is_probable_spam({"symbol": "CLAIM", "decimals": 18, "name": "visit x.xyz"})
    assert is_probable_spam({"symbol": "", "decimals": 18})        # no symbol
    assert is_probable_spam({"symbol": "OK", "decimals": None})    # no decimals
    assert is_probable_spam({"isSpam": True, "symbol": "OK", "decimals": 18})


def test_evm_discovery_filters_zero_and_spam():
    from sources.evm_source import EvmSource

    USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    SPAM = "0x00000000000000000000000000000000deadbeef"

    def rpc(method, params):
        if method == "eth_getBalance":
            return hex(5 * 10**17)
        if method == "alchemy_getTokenBalances":
            return {"tokenBalances": [
                {"contractAddress": USDC, "tokenBalance": hex(100 * 10**6)},
                {"contractAddress": SPAM, "tokenBalance": hex(10**18)},
                {"contractAddress": "0xa", "tokenBalance": "0x0"},
            ]}
        if method == "alchemy_getTokenMetadata":
            if params[0] == USDC:
                return {"symbol": "USDC", "decimals": 6, "name": "USD Coin"}
            return {"symbol": "CLAIM", "decimals": 18, "name": "visit claim.xyz"}

    hs = EvmSource("wallet_01", "0xowner", rpc=rpc).fetch_holdings()
    assert {h.symbol for h in hs} == {"ETH", "USDC"}
    assert next(h for h in hs if h.symbol == "USDC").is_stablecoin


# ── Alpaca degradation ───────────────────────────────────────────────────────


def test_alpaca_no_creds_is_empty():
    from sources.alpaca_source import AlpacaSource

    assert AlpacaSource(api_key_id=None, api_secret_key=None).fetch_holdings() == []


# ── CoinGecko cache ──────────────────────────────────────────────────────────


def test_coingecko_caches_within_run():
    from pricing.coingecko import CoinGeckoPricer

    calls = {"n": 0}
    USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

    def http(path, params):
        calls["n"] += 1
        return {USDC: {"usd": 1.0, "last_updated_at": 1717545600}}

    p = CoinGeckoPricer(http=http)
    a = p.price_contracts([USDC])
    b = p.price_contracts([USDC])
    assert a[USDC].price_usd == Decimal("1.0")
    assert b[USDC].price_usd == Decimal("1.0")
    assert calls["n"] == 1  # second lookup served from cache


# ── Target classification ────────────────────────────────────────────────────


def test_classify_above_and_below():
    from targets import classify, FAR, NEAR, HIT

    d = lambda x: Decimal(str(x))
    # above: target 100, 2% band -> near in [98,100)
    assert classify(d(101), d(100), "above", d(2)) == HIT
    assert classify(d(99), d(100), "above", d(2)) == NEAR
    assert classify(d(97), d(100), "above", d(2)) == FAR
    # below: target 100, near in (100,102]
    assert classify(d(99), d(100), "below", d(2)) == HIT
    assert classify(d(101), d(100), "below", d(2)) == NEAR
    assert classify(d(103), d(100), "below", d(2)) == FAR


# ── Net-worth pct ────────────────────────────────────────────────────────────


def test_networth_pct_change():
    from alerts.networth import _pct_change

    assert _pct_change(Decimal("100"), Decimal("110")) == pytest.approx(10.0)
    assert _pct_change(Decimal("0"), Decimal("5")) == float("inf")


def test_telegram_disabled_degrades():
    from alerts.telegram import TelegramNotifier

    n = TelegramNotifier(bot_token=None)
    assert n.enabled is False
    assert n.send_urgent("x") is False  # logs, does not raise


# ── Per-source isolation (D8 done-when) ──────────────────────────────────────


def test_per_source_isolation(monkeypatch):
    """One source raising must not stop the others; failure is recorded."""
    import ingest
    from sources.base import Holding

    class GoodSource:
        key = "wallet_standard"
        def fetch_holdings(self):
            return [Holding.from_raw(source=self.key, asset_class="crypto_spot",
                    symbol="ETH", raw_quantity=10**18, decimals=18,
                    chain="base", address=config.NATIVE_ETH_SENTINEL.lower(),
                    coingecko_id="ethereum")]

    class BadSource:
        key = "wallet_01"
        def fetch_holdings(self):
            raise RuntimeError("rpc exploded")

    monkeypatch.setattr("sources.alpaca_source.build_alpaca_source",
                        lambda s=None: None)
    monkeypatch.setattr("sources.evm_source.build_evm_sources",
                        lambda s=None: [GoodSource(), BadSource()])

    holdings, status = ingest.collect_holdings(config.settings)
    assert [h.symbol for h in holdings] == ["ETH"]      # good source survived
    assert status["wallet_standard"] == "ok"
    assert status["wallet_01"].startswith("failed:")    # bad source recorded


# ── Watchlist-request validators (pure) ──────────────────────────────────────


def test_normalize_equity_symbol():
    from watchlist_requests import normalize_equity_symbol

    assert normalize_equity_symbol("nvda") == "NVDA"
    assert normalize_equity_symbol("  brk.b ") == "BRK.B"
    with pytest.raises(ValueError):
        normalize_equity_symbol("")
    with pytest.raises(ValueError):
        normalize_equity_symbol("not a ticker!")


def test_normalize_token_address():
    from watchlist_requests import normalize_token_address

    good = "0x" + "Ab" * 20
    assert normalize_token_address(good) == good.lower()
    with pytest.raises(ValueError):
        normalize_token_address("0xnothex")
    with pytest.raises(ValueError):
        normalize_token_address("")


# ── DB-gated: instrument round-trip is idempotent ────────────────────────────


def test_get_or_create_idempotent(db_conn):
    from db import client as db

    a = db.get_or_create_instrument(db_conn, asset_class="equity", symbol="ZZZT")
    b = db.get_or_create_instrument(db_conn, asset_class="equity", symbol="ZZZT")
    assert a == b
    db_conn.rollback()
