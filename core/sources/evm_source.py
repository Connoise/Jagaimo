"""EVM (Base) holdings adapter — read-only.

Primary path: Alchemy `alchemy_getTokenBalances` + `alchemy_getTokenMetadata`
(decision §2.6), with spam filtering. Native ETH via `eth_getBalance`.

Fallback path: a public Base RPC + an explicit `TOKEN_ALLOWLIST`, reading each
token's `balanceOf` via web3.py.

Both wallets reuse this adapter — a wallet is just an address. There are no
write/transfer calls anywhere in this module (grep-verifiable per §10).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

import requests

import config
from sources.base import Holding

log = logging.getLogger("jagaimo.evm")

ALCHEMY_BASE_URL = "https://base-mainnet.g.alchemy.com/v2/{key}"

# Minimal ERC-20 ABI for the public-RPC fallback (read-only views only).
ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}],
     "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol",
     "outputs": [{"name": "", "type": "string"}], "type": "function"},
]

# Words that strongly indicate an airdropped-scam token name/symbol.
_SPAM_HINTS = ("http", "www.", ".com", ".io", ".xyz", "visit", "claim",
               "reward", "airdrop", "voucher", "$")


# ── Pure helpers (no I/O — unit tested offline) ──────────────────────────────


def hex_to_int(value: str | int | None) -> int:
    """Parse a JSON-RPC hex quantity (or passthrough int) to int. None → 0."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    value = value.strip()
    if value in ("", "0x", "0x0"):
        return 0
    return int(value, 16)


def is_probable_spam(metadata: dict[str, Any]) -> bool:
    """Heuristic + explicit-flag spam filter for a token's metadata.

    Drops tokens that Alchemy flags as spam, or that lack usable metadata, or
    whose name/symbol look like the classic "visit site to claim" scam.
    """
    if metadata.get("isSpam") is True:
        return True
    symbol = (metadata.get("symbol") or "").strip()
    decimals = metadata.get("decimals")
    if not symbol or decimals is None:
        return True
    if len(symbol) > 16:
        return True
    haystack = f"{symbol} {(metadata.get('name') or '')}".lower()
    return any(hint in haystack for hint in _SPAM_HINTS)


def _is_stable(symbol: str) -> bool:
    return symbol.upper() in config.STABLECOIN_SYMBOLS


def build_token_holding(
    *, source: str, contract: str, raw_balance: int, metadata: dict[str, Any]
) -> Holding | None:
    """Turn a (contract, raw balance, metadata) triple into a Holding.

    Returns None for zero balances or spam — those are skipped, not errored.
    """
    if raw_balance <= 0:
        return None
    if is_probable_spam(metadata):
        log.debug("skipping spam/low-info token %s", contract)
        return None
    symbol = metadata["symbol"].strip()
    decimals = int(metadata["decimals"])
    return Holding.from_raw(
        source=source,
        asset_class="crypto_spot",
        symbol=symbol,
        raw_quantity=raw_balance,
        decimals=decimals,
        chain=config.BASE_CHAIN,
        address=contract,
        is_stablecoin=_is_stable(symbol),
        display_name=metadata.get("name"),
        metadata={"discovered": "evm"},
    )


def build_native_holding(source: str, raw_wei: int) -> Holding | None:
    """Native ETH holding from a raw wei balance (None if zero)."""
    if raw_wei <= 0:
        return None
    return Holding.from_raw(
        source=source,
        asset_class="crypto_spot",
        symbol="ETH",
        raw_quantity=raw_wei,
        decimals=18,
        chain=config.BASE_CHAIN,
        address=config.NATIVE_ETH_SENTINEL.lower(),
        coingecko_id="ethereum",
        display_name="Ethereum (native, Base)",
        metadata={"native": True},
    )


# ── Source implementation ────────────────────────────────────────────────────

# An RPC transport maps (method, params) -> JSON-RPC `result`. Injectable so the
# discovery logic can be exercised without a live endpoint.
RpcTransport = Callable[[str, list[Any]], Any]


class EvmSource:
    """Read-only Base balances for a single address."""

    def __init__(
        self,
        source_key: str,
        address: str,
        *,
        alchemy_api_key: str | None = None,
        base_rpc_url: str | None = None,
        token_allowlist: Iterable[str] | None = None,
        rpc: RpcTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.key = source_key
        self.address = address
        self.alchemy_api_key = alchemy_api_key
        self.base_rpc_url = base_rpc_url
        self.token_allowlist = [a.lower() for a in (token_allowlist or [])]
        self.timeout = timeout
        self._session = requests.Session()
        # Custom transport wins (tests); else build the Alchemy JSON-RPC caller.
        self._rpc = rpc or (self._alchemy_rpc if alchemy_api_key else None)

    # -- transports --
    def _alchemy_rpc(self, method: str, params: list[Any]) -> Any:
        url = ALCHEMY_BASE_URL.format(key=self.alchemy_api_key)
        resp = self._session.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if "error" in payload and payload["error"]:
            raise RuntimeError(f"Alchemy RPC error for {method}: {payload['error']}")
        return payload.get("result")

    # -- discovery --
    def fetch_holdings(self) -> list[Holding]:
        if self._rpc is not None:
            return self._fetch_via_rpc()
        if self.base_rpc_url:
            return self._fetch_via_web3()
        raise config.ConfigError(
            f"EVM source {self.key}: no Alchemy key and no BASE_RPC_URL."
        )

    def _fetch_via_rpc(self) -> list[Holding]:
        """Alchemy (or injected transport) discovery path."""
        assert self._rpc is not None
        holdings: list[Holding] = []

        native = build_native_holding(
            self.key, hex_to_int(self._rpc("eth_getBalance", [self.address, "latest"]))
        )
        if native:
            holdings.append(native)

        result = self._rpc("alchemy_getTokenBalances", [self.address, "erc20"]) or {}
        for tb in result.get("tokenBalances", []):
            contract = tb.get("contractAddress")
            raw = hex_to_int(tb.get("tokenBalance"))
            if not contract or raw <= 0:
                continue
            meta = self._rpc("alchemy_getTokenMetadata", [contract]) or {}
            holding = build_token_holding(
                source=self.key, contract=contract, raw_balance=raw, metadata=meta
            )
            if holding:
                holdings.append(holding)
        log.info("%s: %d holdings via RPC discovery", self.key, len(holdings))
        return holdings

    def _fetch_via_web3(self) -> list[Holding]:
        """Public-RPC fallback: native + each allowlisted token's balanceOf."""
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(self.base_rpc_url,
                                    request_kwargs={"timeout": self.timeout}))
        owner = Web3.to_checksum_address(self.address)
        holdings: list[Holding] = []

        native = build_native_holding(self.key, int(w3.eth.get_balance(owner)))
        if native:
            holdings.append(native)

        if not self.token_allowlist:
            log.warning("%s: public-RPC path with empty TOKEN_ALLOWLIST — "
                        "only native ETH discovered.", self.key)

        for contract in self.token_allowlist:
            try:
                c = w3.eth.contract(
                    address=Web3.to_checksum_address(contract), abi=ERC20_ABI
                )
                raw = int(c.functions.balanceOf(owner).call())
                if raw <= 0:
                    continue
                meta = {
                    "symbol": c.functions.symbol().call(),
                    "decimals": int(c.functions.decimals().call()),
                }
                holding = build_token_holding(
                    source=self.key, contract=contract, raw_balance=raw, metadata=meta
                )
                if holding:
                    holdings.append(holding)
            except Exception as exc:  # one bad token must not sink the wallet
                log.warning("%s: token %s read failed: %s", self.key, contract, exc)
        log.info("%s: %d holdings via public RPC", self.key, len(holdings))
        return holdings


def build_evm_sources(settings: config.Config | None = None) -> list[EvmSource]:
    """Construct an EvmSource per configured wallet from settings."""
    settings = settings or config.settings
    if not settings.evm_enabled:
        return []
    return [
        EvmSource(
            source_key=key,
            address=address,
            alchemy_api_key=settings.alchemy_api_key,
            base_rpc_url=settings.base_rpc_url,
            token_allowlist=settings.token_allowlist,
        )
        for key, address in settings.wallets
    ]
