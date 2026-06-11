"""Vanguard CSV source — file-based holdings snapshots + transaction imports.

Vanguard exposes no public retail API, so this integration is file-based by
design (no aggregator service): export from vanguard.com (My Accounts →
Transaction history → Download → CSV) and drop the file(s) into
`VANGUARD_CSV_DIR`. A single export may contain a *holdings* section and/or a
*transactions* section — both are understood:

  * holdings → this module is a regular `Source`. Each ingest run re-reads the
    newest export and emits the positions as the snapshot; between exports the
    file is the last known truth.
  * transactions → appended to the `tracking.transactions` ledger (see
    `ledger.py`), deduplicated by a deterministic natural key so overlapping
    re-exports never double-count.

Pricing: the exported price ages between exports. Equity/ETF rows are
re-priced live via Alpaca market data each run (ingest.reprice_csv_equities);
mutual funds (no Alpaca quotes) keep the exported NAV as `last_close` until
the file exceeds VANGUARD_CSV_STALE_DAYS, then flip to `stale_unlisted` so the
issues indicator nudges a re-export.

Known limits (documented, not worked around): Vanguard exports only the last
~18 months of transactions to CSV, and non-ticker holdings (CDs, bonds) are
skipped with a warning.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import config
from sources.base import Holding

log = logging.getLogger("jagaimo.vanguard")

# Mutual-fund share classes follow the 5-letters-ending-in-X convention
# (VTSAX, VMFXX). ETFs/stocks can't be told apart from the CSV → 'equity',
# matching the Alpaca source's default so the same ticker held at both
# brokers resolves to the same instrument.
_FUND_SYMBOL_RE = re.compile(r"^[A-Z]{4}X$")

# Canonical column names ← the header variants Vanguard has shipped.
_COLUMN_ALIASES: dict[str, str] = {
    "account number": "account",
    "fund account number": "account",
    "investment name": "name",
    "fund name": "name",
    "security name": "name",
    "security description": "name",
    "symbol": "symbol",
    "ticker": "symbol",
    "shares": "shares",
    "quantity": "shares",
    "share price": "price",
    "price": "price",
    "total value": "value",
    "market value": "value",
    "value": "value",
    "trade date": "trade_date",
    "date": "trade_date",
    "settlement date": "settlement_date",
    "transaction type": "type",
    "transaction description": "description",
    "principal amount": "principal",
    "gross amount": "principal",
    "commission fees": "fees",
    "commission and fees": "fees",
    "commissions and fees": "fees",
    "commission": "fees",
    "fees": "fees",
    "net amount": "amount",
    "amount": "amount",
    "accrued interest": "accrued_interest",
    "account type": "account_type",
}


@dataclass
class ParsedHolding:
    account: str | None
    name: str | None
    symbol: str | None
    shares: Decimal | None
    price: Decimal | None
    value: Decimal | None


@dataclass
class ParsedTxn:
    account: str | None
    trade_date: datetime | None       # date precision, stored as 00:00 UTC
    settlement_date: datetime | None
    type: str | None
    description: str | None
    name: str | None
    symbol: str | None
    shares: Decimal | None
    price: Decimal | None
    fees: Decimal | None
    amount: Decimal | None            # signed net (negative = cash out)


@dataclass
class ParsedExport:
    holdings: list[ParsedHolding] = field(default_factory=list)
    transactions: list[ParsedTxn] = field(default_factory=list)


# ── Cell-level parsing ────────────────────────────────────────────────────────


def _norm_header(cell: str) -> str:
    """Normalize a header cell for alias lookup ("Share  Price " → "share price")."""
    return re.sub(r"[^a-z0-9]+", " ", cell.lower()).strip()


def _money(raw: str | None) -> Decimal | None:
    """Parse Vanguard money/quantity cells: "$1,234.56", "(12.50)", "—", ""."""
    s = (raw or "").strip().replace("$", "").replace(",", "")
    if not s or s in {"-", "—", "N/A", "n/a"}:
        return None
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


def _date(raw: str | None) -> datetime | None:
    """Parse a CSV date to 00:00 UTC (the export carries no time component)."""
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            d = datetime.strptime(s, fmt)
            return d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _text(raw: str | None) -> str | None:
    s = (raw or "").strip()
    return s or None


# ── Section-aware export parser ──────────────────────────────────────────────


def _canonical_header(cells: list[str]) -> dict[int, str]:
    """Map column index → canonical name for recognized columns."""
    out: dict[int, str] = {}
    for i, cell in enumerate(cells):
        canon = _COLUMN_ALIASES.get(_norm_header(cell))
        if canon and canon not in out.values():
            out[i] = canon
    return out


def _is_txn_header(cols: set[str]) -> bool:
    return "trade_date" in cols and "type" in cols


def _is_holdings_header(cols: set[str]) -> bool:
    return (
        "shares" in cols
        and "price" in cols
        and "value" in cols
        and ("symbol" in cols or "name" in cols)
        and "trade_date" not in cols
        and "type" not in cols
    )


def parse_export(text: str) -> ParsedExport:
    """Parse a Vanguard CSV export (holdings and/or transactions sections).

    Sections are detected by their header rows; anything before, between, or
    after recognized sections is ignored, so format drift degrades gracefully
    instead of erroring.
    """
    rows = list(csv.reader(io.StringIO(text)))
    export = ParsedExport()

    i = 0
    while i < len(rows):
        header = _canonical_header(rows[i])
        cols = set(header.values())
        if _is_txn_header(cols):
            i = _consume_section(rows, i + 1, header, export.transactions, _txn_row)
        elif _is_holdings_header(cols):
            i = _consume_section(rows, i + 1, header, export.holdings, _holding_row)
        else:
            i += 1
    return export


def _consume_section(rows, start, header, out: list, build) -> int:
    """Append built rows until a blank line / new header; return the next index."""
    i = start
    while i < len(rows):
        cells = rows[i]
        if not any(c.strip() for c in cells):
            return i + 1  # blank separator ends the section
        if _canonical_header(cells).keys() and not any(
            _money(cells[j]) is not None or _date(cells[j]) is not None
            for j in range(len(cells))
        ):
            return i  # looks like the next section's header — re-examine it
        record = {name: cells[j] if j < len(cells) else "" for j, name in header.items()}
        built = build(record)
        if built is not None:
            out.append(built)
        i += 1
    return i


def _holding_row(r: dict[str, str]) -> ParsedHolding | None:
    shares = _money(r.get("shares"))
    value = _money(r.get("value"))
    if shares is None and value is None:
        return None
    return ParsedHolding(
        account=_text(r.get("account")),
        name=_text(r.get("name")),
        symbol=(_text(r.get("symbol")) or "").upper() or None,
        shares=shares,
        price=_money(r.get("price")),
        value=value,
    )


def _txn_row(r: dict[str, str]) -> ParsedTxn | None:
    trade_date = _date(r.get("trade_date"))
    txn_type = _text(r.get("type"))
    if trade_date is None or txn_type is None:
        return None
    return ParsedTxn(
        account=_text(r.get("account")),
        trade_date=trade_date,
        settlement_date=_date(r.get("settlement_date")),
        type=txn_type,
        description=_text(r.get("description")),
        name=_text(r.get("name")),
        symbol=(_text(r.get("symbol")) or "").upper() or None,
        shares=_money(r.get("shares")),
        price=_money(r.get("price")),
        fees=_money(r.get("fees")),
        amount=_money(r.get("amount")),
    )


# ── Classification ───────────────────────────────────────────────────────────


def classify_symbol(symbol: str | None, name: str = "") -> str:
    """Asset class for a Vanguard row: 'cash' | 'fund' | 'equity'."""
    if not symbol:
        lowered = name.lower()
        if "cash" in lowered or "sweep" in lowered:
            return "cash"
        return "equity"  # caller decides whether a no-symbol row is usable
    if _FUND_SYMBOL_RE.match(symbol):
        return "fund"
    return "equity"


def classify_side(txn_type: str) -> str:
    """Normalize a Vanguard transaction type to the ledger's side enum.

    Reinvestments are buys (they purchase shares). Sweeps/transfers/exchanges
    stay 'other' — the raw type is preserved in `kind`, and guessing direction
    from share signs would misclassify legitimate edge cases.
    """
    t = txn_type.lower()
    if any(k in t for k in ("buy", "purchase", "reinvest")):
        return "buy"
    if any(k in t for k in ("sell", "redemption", "sale")):
        return "sell"
    if any(k in t for k in ("dividend", "interest", "capital gain", "distribution")):
        return "income"
    return "other"


# ── Holdings source (Source protocol) ────────────────────────────────────────


def _candidate_files(path_str: str) -> list[Path]:
    """CSV files at the configured path (file or directory), newest first."""
    path = Path(path_str).expanduser()
    if path.is_file():
        return [path]
    if path.is_dir():
        files = [p for p in path.iterdir()
                 if p.is_file() and p.suffix.lower() == ".csv"]
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    return []


class VanguardCsvSource:
    """Positions from the newest Vanguard CSV export containing holdings."""

    key = config.SOURCE_VANGUARD

    def __init__(self, csv_path: str, *, stale_days: int | None = None) -> None:
        self.csv_path = csv_path
        self.stale_days = (
            stale_days if stale_days is not None else config.VANGUARD_CSV_STALE_DAYS
        )

    def fetch_holdings(self) -> list[Holding]:
        for path in _candidate_files(self.csv_path):
            try:
                export = parse_export(path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                log.warning("vanguard: could not parse %s: %s", path.name, exc)
                continue
            if export.holdings:
                return self._to_holdings(export.holdings, path)
        log.info("vanguard: no export with a holdings section in %s", self.csv_path)
        return []

    def _to_holdings(self, parsed: list[ParsedHolding], path: Path) -> list[Holding]:
        exported_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age_days = (datetime.now(timezone.utc) - exported_at).days
        fresh = age_days <= self.stale_days
        if not fresh:
            log.warning(
                "vanguard: %s is %d days old (> %d) — unquoted rows marked stale",
                path.name, age_days, self.stale_days,
            )

        # Aggregate per (symbol, asset_class) across accounts; per-account
        # quantities are kept in metadata for transparency.
        agg: dict[tuple[str, str], dict] = {}
        cash_total = Decimal("0")
        for row in parsed:
            asset_class = classify_symbol(row.symbol, row.name or "")
            if asset_class == "cash":
                cash_total += row.value if row.value is not None else (row.shares or 0)
                continue
            if not row.symbol:
                log.warning(
                    "vanguard: skipping non-ticker holding %r (CDs/bonds are "
                    "not supported yet)", row.name,
                )
                continue
            if not row.shares:
                continue
            entry = agg.setdefault(
                (row.symbol, asset_class),
                {"shares": Decimal("0"), "price": None, "name": row.name,
                 "accounts": {}},
            )
            entry["shares"] += row.shares
            entry["price"] = row.price if row.price is not None else entry["price"]
            acct = row.account or "?"
            entry["accounts"][acct] = str(
                Decimal(entry["accounts"].get(acct, "0")) + row.shares
            )

        meta_common = {"file": path.name, "exported_at": exported_at.isoformat()}
        holdings: list[Holding] = []
        for (symbol, asset_class), entry in agg.items():
            price = entry["price"]
            if price is None:
                status = config.PRICE_UNPRICED
            elif fresh:
                status = config.PRICE_LAST_CLOSE
            else:
                status = config.PRICE_STALE_UNLISTED
            holdings.append(
                Holding(
                    source=self.key,
                    asset_class=asset_class,
                    symbol=symbol,
                    quantity=entry["shares"],
                    display_name=entry["name"],
                    price_usd=price,
                    price_as_of=exported_at,
                    price_status=status,
                    metadata={**meta_common, "accounts": entry["accounts"]},
                )
            )
        if cash_total:
            holdings.append(
                Holding(
                    source=self.key,
                    asset_class="cash",
                    symbol="USD",
                    quantity=cash_total,
                    display_name="US Dollar (Vanguard cash)",
                    price_usd=Decimal("1"),
                    price_as_of=exported_at,
                    price_status=config.PRICE_LIVE,
                    metadata={**meta_common, "kind": "cash"},
                )
            )
        log.info("vanguard: %d holdings from %s (age %dd)",
                 len(holdings), path.name, age_days)
        return holdings


def build_vanguard_source(
    settings: config.Config | None = None,
) -> VanguardCsvSource | None:
    settings = settings or config.settings
    if not settings.vanguard_enabled:
        return None
    return VanguardCsvSource(settings.vanguard_csv_path)


# ── Transactions → ledger rows ───────────────────────────────────────────────


def _decimal_key(value: Decimal | None) -> str:
    """Canonical text for a Decimal so 10.0 and 10.00 hash identically."""
    if value is None:
        return ""
    return format(value.normalize(), "f")


def transactions_to_rows(
    txns: list[ParsedTxn], *, resolve_instrument
) -> list[dict]:
    """Build `tracking.transactions` rows from parsed Vanguard transactions.

    `resolve_instrument(symbol, asset_class) -> int | None` links rows to the
    same instruments the holdings path creates (None for cash-only rows).

    Dedup key: the logical row's fields plus an occurrence index *within this
    export*, so two genuinely identical same-day rows in one file both import,
    while the same row re-exported in an overlapping date range collides and
    is skipped by ON CONFLICT.
    """
    seen: dict[str, int] = {}
    rows: list[dict] = []
    for t in txns:
        if t.trade_date is None or t.type is None:
            continue
        instrument_id = None
        if t.symbol:
            instrument_id = resolve_instrument(
                t.symbol, classify_symbol(t.symbol, t.name or "")
            )
        base = "|".join([
            "vg",
            t.account or "",
            t.trade_date.date().isoformat(),
            t.type.strip().lower(),
            t.symbol or "",
            _decimal_key(t.shares),
            _decimal_key(t.amount),
        ])
        occurrence = seen[base] = seen.get(base, 0) + 1
        rows.append({
            "source": config.SOURCE_VANGUARD,
            "account": t.account,
            "instrument_id": instrument_id,
            "symbol": t.symbol,
            "trade_ts": t.trade_date,
            "settlement_ts": t.settlement_date,
            "side": classify_side(t.type),
            "kind": t.type,
            "quantity": t.shares,
            "price_usd": t.price,
            "fees_usd": t.fees,
            "amount_usd": t.amount,
            "description": t.description or t.name,
            "natural_key": "vg:" + hashlib.sha256(
                f"{base}|{occurrence}".encode()
            ).hexdigest(),
        })
    return rows


# ── CLI: validate / import an export by hand ─────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Parse Vanguard CSV export(s); import transactions into "
        "the ledger (ingest also does this automatically every run)."
    )
    parser.add_argument("paths", nargs="*", help="CSV files (default: VANGUARD_CSV_DIR)")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and summarize only; no DB writes")
    args = parser.parse_args()

    paths = [Path(p) for p in args.paths]
    if not paths:
        if not config.settings.vanguard_enabled:
            print("No paths given and VANGUARD_CSV_DIR is not set.", file=sys.stderr)
            sys.exit(2)
        paths = _candidate_files(config.settings.vanguard_csv_path)
    if not paths:
        print("No CSV files found.", file=sys.stderr)
        sys.exit(2)

    for p in paths:
        export = parse_export(p.read_text(encoding="utf-8-sig"))
        print(f"{p.name}: {len(export.holdings)} holdings, "
              f"{len(export.transactions)} transactions")
        if args.dry_run:
            continue
        if not export.transactions:
            continue
        from db import client as db

        config.settings.require("database_url")
        with db.connection() as conn:
            def _resolve(symbol: str, asset_class: str) -> int:
                return db.get_or_create_instrument(
                    conn, asset_class=asset_class, symbol=symbol
                )

            rows = transactions_to_rows(export.transactions, resolve_instrument=_resolve)
            inserted = db.insert_transactions(conn, rows)
            print(f"  → {inserted} new ledger rows ({len(rows) - inserted} duplicates skipped)")
