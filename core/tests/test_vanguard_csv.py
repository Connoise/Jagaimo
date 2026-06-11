"""Offline tests for the Vanguard CSV parser, source, and ledger-row builder."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import config
from sources.vanguard_csv import (
    VanguardCsvSource,
    classify_side,
    classify_symbol,
    parse_export,
    transactions_to_rows,
)

# A combined export the way Vanguard ships them: holdings section, blank line,
# transactions section; trailing commas; $ and parenthesized negatives mixed in.
COMBINED_CSV = """\
Account Number,Investment Name,Symbol,Shares,Share Price,Total Value,
12345678,VANGUARD TOTAL STOCK MARKET INDEX ADMIRAL,VTSAX,100.5,"$118.50","$11,909.25",
12345678,VANGUARD TOTAL STOCK MARKET ETF,VTI,10,240.00,2400.00,
87654321,VANGUARD TOTAL STOCK MARKET ETF,VTI,5,240.00,1200.00,
12345678,APPLE INC,AAPL,8,200.00,1600.00,
12345678,VANGUARD FEDERAL MONEY MARKET FUND,VMFXX,500.00,1.00,500.00,
12345678,CASH SWEEP,,250.00,1.00,250.00,
12345678,U S TREASURY NOTE 4.5%,,1000,99.50,995.00,

Account Number,Trade Date,Settlement Date,Transaction Type,Transaction Description,Investment Name,Symbol,Shares,Share Price,Principal Amount,Commission Fees,Net Amount,Accrued Interest,Account Type,
12345678,01/02/2025,01/03/2025,Buy,Buy,VANGUARD TOTAL STOCK MARKET ETF,VTI,10,240.00,(2400.00),0.00,(2400.00),0.00,CASH,
12345678,01/02/2025,01/03/2025,Buy,Buy,VANGUARD TOTAL STOCK MARKET ETF,VTI,10,240.00,(2400.00),0.00,(2400.00),0.00,CASH,
12345678,02/14/2025,02/14/2025,Dividend,Dividend Received,APPLE INC,AAPL,0,0.00,12.34,0.00,12.34,0.00,CASH,
12345678,03/01/2025,03/03/2025,Sell,Sell,APPLE INC,AAPL,2,210.00,420.00,0.00,420.00,0.00,CASH,
12345678,03/05/2025,03/05/2025,Reinvestment,Dividend Reinvestment,VANGUARD TOTAL STOCK MARKET INDEX ADMIRAL,VTSAX,0.5,119.00,(59.50),0.00,(59.50),0.00,CASH,
12345678,03/10/2025,03/10/2025,Sweep in,Sweep into settlement fund,VANGUARD FEDERAL MONEY MARKET FUND,VMFXX,100,1.00,(100.00),0.00,(100.00),0.00,CASH,
"""


# ── Parsing ──────────────────────────────────────────────────────────────────


def test_parse_combined_export_sections():
    export = parse_export(COMBINED_CSV)
    assert len(export.holdings) == 7
    assert len(export.transactions) == 6


def test_parse_holdings_values():
    export = parse_export(COMBINED_CSV)
    vtsax = next(h for h in export.holdings if h.symbol == "VTSAX")
    assert vtsax.shares == Decimal("100.5")
    assert vtsax.price == Decimal("118.50")      # "$118.50" cleaned
    assert vtsax.value == Decimal("11909.25")    # "$11,909.25" cleaned
    assert vtsax.account == "12345678"


def test_parse_txn_values_and_negatives():
    export = parse_export(COMBINED_CSV)
    buy = export.transactions[0]
    assert buy.trade_date == datetime(2025, 1, 2, tzinfo=timezone.utc)
    assert buy.settlement_date == datetime(2025, 1, 3, tzinfo=timezone.utc)
    assert buy.type == "Buy"
    assert buy.symbol == "VTI"
    assert buy.shares == Decimal("10")
    assert buy.amount == Decimal("-2400.00")     # parenthesized negative


def test_parse_holdings_only_export():
    holdings_only = COMBINED_CSV.split("\n\n")[0]
    export = parse_export(holdings_only)
    assert len(export.holdings) == 7
    assert export.transactions == []


# ── Classification ───────────────────────────────────────────────────────────


def test_classify_symbol():
    assert classify_symbol("VTSAX") == "fund"     # 5 letters ending in X
    assert classify_symbol("VMFXX") == "fund"
    assert classify_symbol("VTI") == "equity"
    assert classify_symbol("AAPL") == "equity"
    assert classify_symbol(None, "Cash sweep") == "cash"


def test_classify_side():
    assert classify_side("Buy") == "buy"
    assert classify_side("Reinvestment (LT gain)") == "buy"
    assert classify_side("Sell") == "sell"
    assert classify_side("Dividend Received") == "income"
    assert classify_side("Capital gain (ST)") == "income"
    assert classify_side("Sweep in") == "other"
    assert classify_side("Funds Received") == "other"


# ── Source: fetch_holdings ───────────────────────────────────────────────────


def _write_export(tmp_path, name="export.csv", text=COMBINED_CSV, age_days=0):
    f = tmp_path / name
    f.write_text(text)
    if age_days:
        old = time.time() - age_days * 86400
        os.utime(f, (old, old))
    return f


def test_source_aggregates_across_accounts(tmp_path):
    _write_export(tmp_path)
    holdings = VanguardCsvSource(str(tmp_path)).fetch_holdings()
    by_symbol = {h.symbol: h for h in holdings}

    vti = by_symbol["VTI"]                        # 10 + 5 across two accounts
    assert vti.quantity == Decimal("15")
    assert vti.asset_class == "equity"
    assert set(vti.metadata["accounts"]) == {"12345678", "87654321"}

    assert by_symbol["VTSAX"].asset_class == "fund"
    assert by_symbol["VTSAX"].price_status == config.PRICE_LAST_CLOSE

    # The no-symbol cash row becomes a USD cash holding, valued 1:1.
    assert by_symbol["USD"].asset_class == "cash"
    assert by_symbol["USD"].quantity == Decimal("250.00")
    assert by_symbol["USD"].price_usd == Decimal("1")

    # The no-ticker treasury note is skipped, not invented.
    assert all(h.symbol for h in holdings)


def test_source_fresh_vs_stale(tmp_path):
    _write_export(tmp_path, age_days=30)
    holdings = VanguardCsvSource(str(tmp_path), stale_days=7).fetch_holdings()
    by_symbol = {h.symbol: h for h in holdings}
    # Old export → unquoted rows flagged stale; cash is still cash.
    assert by_symbol["VTSAX"].price_status == config.PRICE_STALE_UNLISTED
    assert by_symbol["USD"].price_status == config.PRICE_LIVE


def test_source_picks_newest_file_with_holdings(tmp_path):
    _write_export(tmp_path, "old.csv", age_days=10)
    txn_only = COMBINED_CSV.split("\n\n")[1]
    _write_export(tmp_path, "new-txns-only.csv", text=txn_only)
    holdings = VanguardCsvSource(str(tmp_path)).fetch_holdings()
    # Newest file has no holdings section → falls back to the older export.
    assert {h.symbol for h in holdings} >= {"VTSAX", "VTI", "AAPL"}


def test_source_empty_dir(tmp_path):
    assert VanguardCsvSource(str(tmp_path)).fetch_holdings() == []


# ── Ledger rows + dedup keys ─────────────────────────────────────────────────


def _rows(txns):
    ids = {}

    def resolve(symbol, asset_class):
        return ids.setdefault((symbol, asset_class), len(ids) + 1)

    return transactions_to_rows(txns, resolve_instrument=resolve)


def test_txn_rows_fields_and_sides():
    export = parse_export(COMBINED_CSV)
    rows = _rows(export.transactions)
    assert len(rows) == 6
    sides = [r["side"] for r in rows]
    assert sides == ["buy", "buy", "income", "sell", "buy", "other"]
    div = rows[2]
    assert div["kind"] == "Dividend"
    assert div["amount_usd"] == Decimal("12.34")
    assert div["source"] == config.SOURCE_VANGUARD
    # Same instrument resolution as the holdings path (fund vs equity).
    vtsax_row = rows[4]
    aapl_row = rows[2]
    assert vtsax_row["instrument_id"] != aapl_row["instrument_id"]


def test_natural_keys_dedupe_across_files_but_not_within():
    export = parse_export(COMBINED_CSV)
    rows_a = _rows(export.transactions)
    rows_b = _rows(parse_export(COMBINED_CSV).transactions)

    keys_a = [r["natural_key"] for r in rows_a]
    # Two identical same-day buys in ONE file get distinct keys (occurrence n).
    assert len(set(keys_a)) == len(keys_a)
    # Re-parsing the same file (an overlapping re-export) reproduces the SAME
    # keys, so ON CONFLICT DO NOTHING drops every duplicate.
    assert keys_a == [r["natural_key"] for r in rows_b]


def test_natural_key_decimal_canonicalization():
    export_a = parse_export(COMBINED_CSV)
    altered = COMBINED_CSV.replace("(2400.00)", "(2400.0)").replace(
        ",10,240.00,", ",10.0,240.00,"
    )
    export_b = parse_export(altered)
    keys_a = [r["natural_key"] for r in _rows(export_a.transactions)]
    keys_b = [r["natural_key"] for r in _rows(export_b.transactions)]
    assert keys_a == keys_b  # 10 vs 10.0 / 2400.00 vs 2400.0 hash identically
