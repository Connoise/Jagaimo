"""Central configuration for the Jagaimo data core.

Importing this module never raises (so `python -c "import config"` always
succeeds and `python config.py` can print a status summary). Required-variable
enforcement is explicit via `validate()` / `require()`, called at runtime by
`ingest.py` — so a missing var fails with a clear message, not an import-time
traceback.

All timestamps in the system are UTC (decision §2.7). Local conversion happens
only in the viewer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Load core/.env if present. python-dotenv is a declared dependency, but we keep
# the import optional so that `import config` works in a bare checkout.
try:  # pragma: no cover - trivial import guard
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:  # pragma: no cover
    pass


def _env(name: str, default: str | None = None) -> str | None:
    """Return a stripped env var, treating empty strings as unset."""
    val = os.getenv(name, default)
    if val is None:
        return None
    val = val.strip()
    return val or None


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw is not None else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw is not None else default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    raw = _env(name)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


# ── Locked constants (decisions §2) ──────────────────────────────────────────

# Native-ETH sentinel address used as `instruments.address` for native ETH on
# Base (decision §2.5). Deliberately not the zero address.
NATIVE_ETH_SENTINEL = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

# Base mainnet chain key stored on crypto instruments.
BASE_CHAIN = "base"

# Snapshot cadence (minutes). Cron drives the actual schedule; this is metadata
# used by the viewer ("meaningful only at timeframes >= snapshot interval").
SNAPSHOT_INTERVAL_MIN = 15

# Net-worth alert thresholds (decision §2.4) — fire when |delta| exceeds BOTH
# the percentage and the absolute dollar floor, respecting the cooldown.
NETWORTH_ALERT_PCT = _env_float("NETWORTH_ALERT_PCT", 5.0)
NETWORTH_ALERT_USD = _env_float("NETWORTH_ALERT_USD", 25.0)
NETWORTH_ALERT_COOLDOWN_MIN = _env_int("NETWORTH_ALERT_COOLDOWN_MIN", 60)

# Per-target re-notify cooldown (minutes). Primary de-dup is the target's
# last_state transition; this only damps flapping around a band edge.
TARGET_ALERT_COOLDOWN_MIN = _env_int("TARGET_ALERT_COOLDOWN_MIN", 60)

# Source keys (also used as `holdings.source` / `transactions.source`).
SOURCE_ALPACA = "alpaca"
SOURCE_WALLET_STANDARD = "wallet_standard"
SOURCE_WALLET_01 = "wallet_01"
SOURCE_VANGUARD = "vanguard"
SOURCE_COINBASE = "coinbase"

# A Vanguard CSV export older than this many days flags its fund/unquoted rows
# `stale_unlisted` so the issues indicator nudges a re-export. Equity/ETF rows
# are re-priced live via Alpaca each run and are unaffected.
VANGUARD_CSV_STALE_DAYS = _env_int("VANGUARD_CSV_STALE_DAYS", 7)

# Price-status enum values (mirror tracking.price_status, decision §2.2).
PRICE_LIVE = "live"
PRICE_LAST_CLOSE = "last_close"
PRICE_STALE_UNLISTED = "stale_unlisted"
PRICE_UNPRICED = "unpriced"
PROBLEM_STATUSES = frozenset({PRICE_STALE_UNLISTED, PRICE_UNPRICED})


# ── Well-known Base instruments (pre-seed so day-one pricing works, §2.1) ─────


@dataclass(frozen=True)
class SeedInstrument:
    asset_class: str
    symbol: str
    chain: str | None
    address: str | None
    decimals: int | None
    coingecko_id: str | None
    is_stablecoin: bool = False
    display_name: str | None = None


# Canonical Base mainnet contract addresses (lowercased for stable matching).
SEED_INSTRUMENTS: tuple[SeedInstrument, ...] = (
    SeedInstrument(
        asset_class="crypto_spot",
        symbol="ETH",
        chain=BASE_CHAIN,
        address=NATIVE_ETH_SENTINEL.lower(),
        decimals=18,
        coingecko_id="ethereum",
        display_name="Ethereum (native, Base)",
    ),
    SeedInstrument(
        asset_class="crypto_spot",
        symbol="WETH",
        chain=BASE_CHAIN,
        address="0x4200000000000000000000000000000000000006",
        decimals=18,
        coingecko_id="weth",
        display_name="Wrapped Ether (Base)",
    ),
    SeedInstrument(
        asset_class="crypto_spot",
        symbol="USDC",
        chain=BASE_CHAIN,
        address="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        decimals=6,
        coingecko_id="usd-coin",
        is_stablecoin=True,
        display_name="USD Coin (Base)",
    ),
    SeedInstrument(
        asset_class="crypto_spot",
        symbol="AERO",
        chain=BASE_CHAIN,
        address="0x940181a94a35a4569e4529a3cdfb74e38fd98631",
        decimals=18,
        coingecko_id="aerodrome-finance",
        display_name="Aerodrome Finance",
    ),
)

# Symbols treated as USD-pegged stablecoins for display grouping (decision §2.9).
# Pricing is always live; this only affects `is_stablecoin` defaulting / display.
STABLECOIN_SYMBOLS = frozenset({"USDC", "USDT", "DAI", "USDBC", "USDS"})

# Coinbase exchange balances are custodial (no contract address), so they are
# priced by CoinGecko **id**. Built-in map for common listings; extend via the
# COINBASE_COINGECKO_IDS env ("SYM:id,SYM:id"). Unknown symbols are recorded
# but `stale_unlisted` until mapped — never fail the run.
COINBASE_COINGECKO_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "POL": "polygon-ecosystem-token",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "UNI": "uniswap",
    "AAVE": "aave",
    "ATOM": "cosmos",
    "ALGO": "algorand",
    "XLM": "stellar",
    "ETC": "ethereum-classic",
    "NEAR": "near",
    "OP": "optimism",
    "ARB": "arbitrum",
    "SUI": "sui",
    "APT": "aptos",
    "FIL": "filecoin",
    "ICP": "internet-computer",
    "HBAR": "hedera-hashgraph",
    "GRT": "the-graph",
    "LDO": "lido-dao",
    "CRV": "curve-dao-token",
    "COMP": "compound-governance-token",
    "MKR": "maker",
    "SHIB": "shiba-inu",
    "PEPE": "pepe",
    "TIA": "celestia",
    "SEI": "sei-network",
    "INJ": "injective-protocol",
    "RNDR": "render-token",
    "CBETH": "coinbase-wrapped-staked-eth",
    "AERO": "aerodrome-finance",
    "USDC": "usd-coin",
    "USDT": "tether",
    "DAI": "dai",
}


# ── Runtime configuration object ─────────────────────────────────────────────


@dataclass
class Config:
    """Snapshot of environment-derived settings, built at import time."""

    database_url: str | None

    alpaca_api_key_id: str | None
    alpaca_api_secret_key: str | None
    alpaca_base_url: str

    alchemy_api_key: str | None
    base_rpc_url: str | None
    token_allowlist: list[str] = field(default_factory=list)

    wallet_standard_address: str | None = None
    wallet_01_address: str | None = None

    # Vanguard is file-based (no public retail API): a directory of CSV exports
    # (or a single file path) dropped in by the user.
    vanguard_csv_path: str | None = None

    # Coinbase CDP key: either the downloaded key json, or the name+secret pair.
    coinbase_key_file: str | None = None
    coinbase_api_key_name: str | None = None
    coinbase_api_private_key: str | None = None
    coinbase_coingecko_overrides: dict[str, str] = field(default_factory=dict)

    coingecko_api_key: str | None = None
    coingecko_pro: bool = False

    telegram_bot_token: str | None = None
    telegram_log_chat_id: str | None = None
    telegram_alert_chat_id: str | None = None

    # ── Derived source toggles ──
    @property
    def alpaca_enabled(self) -> bool:
        return bool(self.alpaca_api_key_id and self.alpaca_api_secret_key)

    @property
    def evm_enabled(self) -> bool:
        """EVM works if we have any wallet AND a way to read balances."""
        has_wallet = bool(self.wallet_standard_address or self.wallet_01_address)
        has_provider = bool(self.alchemy_api_key or self.base_rpc_url)
        return has_wallet and has_provider

    @property
    def use_alchemy(self) -> bool:
        return bool(self.alchemy_api_key)

    @property
    def vanguard_enabled(self) -> bool:
        return bool(self.vanguard_csv_path)

    @property
    def coinbase_enabled(self) -> bool:
        return bool(
            self.coinbase_key_file
            or (self.coinbase_api_key_name and self.coinbase_api_private_key)
        )

    def coinbase_coingecko_id(self, symbol: str) -> str | None:
        """CoinGecko id for a Coinbase asset symbol (env overrides win)."""
        sym = symbol.upper()
        return self.coinbase_coingecko_overrides.get(sym) or \
            COINBASE_COINGECKO_IDS.get(sym)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def wallets(self) -> list[tuple[str, str]]:
        """(source_key, address) pairs for every configured wallet."""
        out: list[tuple[str, str]] = []
        if self.wallet_standard_address:
            out.append((SOURCE_WALLET_STANDARD, self.wallet_standard_address))
        if self.wallet_01_address:
            out.append((SOURCE_WALLET_01, self.wallet_01_address))
        return out

    def require(self, *names: str) -> None:
        """Raise a clear error if any named attribute is unset."""
        missing = [n for n in names if not getattr(self, n, None)]
        if missing:
            raise ConfigError(
                "Missing required configuration: "
                + ", ".join(sorted(missing))
                + ". Set these in core/.env (see core/.env.example)."
            )

    def validate(self) -> list[str]:
        """Enforce hard requirements; return a list of non-fatal warnings.

        Raises ConfigError on anything that makes a run impossible.
        """
        # DATABASE_URL is the only universally required secret.
        self.require("database_url")

        warnings: list[str] = []
        if not self.alpaca_enabled:
            warnings.append("Alpaca disabled (no API keys) — equities skipped.")
        if not self.evm_enabled:
            warnings.append(
                "EVM disabled — need a wallet address AND (ALCHEMY_API_KEY or "
                "BASE_RPC_URL). Wallets skipped."
            )
        elif not self.use_alchemy and not self.token_allowlist:
            warnings.append(
                "Public-RPC EVM path without TOKEN_ALLOWLIST — only native ETH "
                "balances will be discovered."
            )
        if not self.telegram_enabled:
            warnings.append("Telegram disabled — alerts will be logged only.")
        if self.vanguard_enabled and not Path(self.vanguard_csv_path).exists():
            warnings.append(
                f"VANGUARD_CSV_DIR set but {self.vanguard_csv_path!r} does not "
                "exist — Vanguard skipped until a CSV export is dropped there."
            )
        if self.coinbase_key_file and not Path(self.coinbase_key_file).exists():
            warnings.append(
                f"COINBASE_KEY_FILE {self.coinbase_key_file!r} does not exist — "
                "Coinbase skipped."
            )
        enabled_sources = (
            self.alpaca_enabled or self.evm_enabled
            or self.vanguard_enabled or self.coinbase_enabled
        )
        if not enabled_sources:
            raise ConfigError(
                "No sources enabled: configure Alpaca, an EVM wallet, "
                "VANGUARD_CSV_DIR, and/or a Coinbase key."
            )
        return warnings


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _parse_id_overrides(raw: str | None) -> dict[str, str]:
    """Parse "SYM:coingecko-id,SYM2:id2" into {SYM: id} (symbols uppercased)."""
    out: dict[str, str] = {}
    for pair in (raw or "").split(","):
        sym, _, cid = pair.partition(":")
        if sym.strip() and cid.strip():
            out[sym.strip().upper()] = cid.strip()
    return out


def load() -> Config:
    """Build a Config from the current environment."""
    # CDP private keys are PEM; when stored inline in .env the newlines arrive
    # as literal "\n" escapes — normalize them back.
    coinbase_secret = _env("COINBASE_API_PRIVATE_KEY")
    if coinbase_secret:
        coinbase_secret = coinbase_secret.replace("\\n", "\n")
    return Config(
        database_url=_env("DATABASE_URL"),
        alpaca_api_key_id=_env("ALPACA_API_KEY_ID"),
        alpaca_api_secret_key=_env("ALPACA_API_SECRET_KEY"),
        alpaca_base_url=_env("ALPACA_BASE_URL") or "https://api.alpaca.markets",
        alchemy_api_key=_env("ALCHEMY_API_KEY"),
        base_rpc_url=_env("BASE_RPC_URL"),
        token_allowlist=[a.lower() for a in _env_list("TOKEN_ALLOWLIST")],
        wallet_standard_address=_env("WALLET_STANDARD_ADDRESS"),
        wallet_01_address=_env("WALLET_01_ADDRESS"),
        vanguard_csv_path=_env("VANGUARD_CSV_DIR"),
        coinbase_key_file=_env("COINBASE_KEY_FILE"),
        coinbase_api_key_name=_env("COINBASE_API_KEY_NAME"),
        coinbase_api_private_key=coinbase_secret,
        coinbase_coingecko_overrides=_parse_id_overrides(
            _env("COINBASE_COINGECKO_IDS")
        ),
        coingecko_api_key=_env("COINGECKO_API_KEY"),
        coingecko_pro=_env_bool("COINGECKO_PRO", False),
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_log_chat_id=_env("TELEGRAM_LOG_CHAT_ID"),
        telegram_alert_chat_id=_env("TELEGRAM_ALERT_CHAT_ID"),
    )


# Module-level singleton — import-safe; does not touch the network or DB.
settings = load()


def _summary() -> str:
    s = settings
    lines = [
        "Jagaimo core configuration",
        "==========================",
        f"  DATABASE_URL set : {bool(s.database_url)}",
        f"  Alpaca enabled   : {s.alpaca_enabled}",
        f"  EVM enabled      : {s.evm_enabled} (alchemy={s.use_alchemy})",
        f"  Wallets          : {[w[0] for w in s.wallets] or 'none'}",
        f"  Vanguard enabled : {s.vanguard_enabled} (csv={s.vanguard_csv_path or '—'})",
        f"  Coinbase enabled : {s.coinbase_enabled}",
        f"  Telegram enabled : {s.telegram_enabled}",
        f"  Net-worth alert  : >{NETWORTH_ALERT_PCT}% AND >${NETWORTH_ALERT_USD}"
        f", cooldown {NETWORTH_ALERT_COOLDOWN_MIN}m",
        f"  Seed instruments : {len(SEED_INSTRUMENTS)}",
    ]
    try:
        warnings = s.validate()
        lines.append("  validate()       : OK")
        for w in warnings:
            lines.append(f"    warning: {w}")
    except ConfigError as exc:
        lines.append(f"  validate()       : FAILED — {exc}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(_summary())
