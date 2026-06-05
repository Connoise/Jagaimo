"""Net-worth threshold alert (decision §2.4).

Fire when total net worth moves **>5% AND >$25** versus the *last alerted*
value (persisted in `tracking.alert_state`), respecting a 60-minute cooldown.
All three constants are tunable in config.

The first ever run just seeds the baseline (no alert). Firing updates the
baseline so the next alert is measured from the last notified value, not from
every snapshot — this is what stops slow drift from spamming.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

import config
from db import client as db

log = logging.getLogger("jagaimo.networth_alert")


def _pct_change(prev: Decimal, curr: Decimal) -> float:
    if prev <= 0:
        return float("inf")
    return abs(float(curr - prev) / float(prev) * 100.0)


def evaluate_networth_alert(
    conn,
    settings: config.Config,
    snapshot_ts: datetime,
    total: Decimal,
    any_problem: bool,
    *,
    notifier=None,
) -> str | None:
    """Return a human-readable description of the alert if one fired, else None."""
    from alerts.telegram import TelegramNotifier

    notifier = notifier or TelegramNotifier()
    state = db.get_alert_state(conn)

    # First run: establish the baseline, do not alert.
    if state.last_alert_value is None:
        db.update_alert_state(conn, total, snapshot_ts)
        log.info("net-worth baseline set at $%.2f", float(total))
        return None

    # Cooldown.
    cooldown = timedelta(minutes=config.NETWORTH_ALERT_COOLDOWN_MIN)
    if state.last_alert_ts and snapshot_ts - state.last_alert_ts < cooldown:
        return None

    prev = state.last_alert_value
    delta = total - prev
    pct = _pct_change(prev, total)
    if abs(delta) > config.NETWORTH_ALERT_USD and pct > config.NETWORTH_ALERT_PCT:
        arrow = "▲" if delta > 0 else "▼"
        flag = "  ⚠️ data issues" if any_problem else ""
        msg = (f"{arrow} Net worth ${float(total):,.2f} "
               f"({'+' if delta>0 else ''}{float(delta):,.2f}, "
               f"{'+' if delta>0 else '-'}{pct:.1f}%) "
               f"since last alert ${float(prev):,.2f}.{flag}")
        notifier.send_urgent(msg)
        db.update_alert_state(conn, total, snapshot_ts)
        log.info("net-worth alert fired: %s", msg)
        return msg
    return None
