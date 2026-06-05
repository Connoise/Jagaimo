"""Pytest bootstrap: ensure `core/` is importable and expose DB availability.

DB-dependent tests skip automatically when DATABASE_URL is unset or the database
is unreachable, so the pure-logic suite runs anywhere (CI included).
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def db_conn():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — skipping DB-backed test")
    from db import client as db

    try:
        conn = db.connect()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"database unreachable: {exc}")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
