"""Price-target evaluation (plan §6 F8 / milestone D6).

Targets are **alerts only** — they notify, never trade (scope §1). Each target
moves through far → near → hit. A notification fires when the state advances to
`near` (Telegram log channel) or `hit` (urgent channel), de-duped by the
target's persisted `last_state` plus a per-target cooldown. Retreats (hit→near,
→far) update `last_state` silently so the target re-arms.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import config
from db import client as db

log = logging.getLogger("jagaimo.targets")

FAR, NEAR, HIT = "far", "near", "hit"
_RANK = {FAR: 0, NEAR: 1, HIT: 2}


def classify(
    price: Decimal, target: Decimal, direction: str, near_pct: Decimal
) -> str:
    """Return far|near|hit for a price relative to a target.

    `direction='above'`: hit when price >= target; near within near_pct *below*
    the target (approaching from beneath). `direction='below'`: hit when
    price <= target; near within near_pct *above* it.
    """
    band = target * (Decimal(near_pct) / Decimal(100))
    if direction == "above":
        if price >= target:
            return HIT
        if price >= target - band:
            return NEAR
        return FAR
    if direction == "below":
        if price <= target:
            return HIT
        if price <= target + band:
            return NEAR
        return FAR
    raise ValueError(f"bad direction: {direction!r}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def evaluate_targets(conn, settings: config.Config, *, notifier=None, now=None) -> int:
    """Evaluate all active targets against latest prices. Returns # notified."""
    from alerts.telegram import TelegramNotifier

    notifier = notifier or TelegramNotifier()
    now = now or _now()
    cooldown = timedelta(minutes=config.TARGET_ALERT_COOLDOWN_MIN)

    prices = db.get_latest_prices(conn)
    instruments = {i.instrument_id: i for i in db.get_instruments(conn)}
    targets = db.get_active_targets(conn)

    notified = 0
    for t in targets:
        price = prices.get(t.instrument_id)
        if price is None:
            continue
        new_state = classify(price, t.target_usd, t.direction, t.near_pct)
        if new_state == t.last_state:
            continue

        advancing = _RANK[new_state] > _RANK[t.last_state]
        cooling = bool(t.last_notified and now - t.last_notified < cooldown)
        sym = instruments[t.instrument_id].symbol if t.instrument_id in instruments else "?"
        label = f" ({t.label})" if t.label else ""

        # HIT always notifies on advance (escalation); NEAR respects cooldown so
        # oscillation around the band edge doesn't spam.
        if new_state in (NEAR, HIT) and advancing and (new_state == HIT or not cooling):
            msg = (f"{sym}{label} {new_state.upper()} target {t.direction} "
                   f"${float(t.target_usd):,.4g} — now ${float(price):,.4g}")
            if new_state == HIT:
                notifier.send_urgent(msg)
            else:
                notifier.send_log(msg)
            db.update_target_state(conn, t.target_id, new_state, now)
            notified += 1
            log.info("target %s -> %s notified", t.target_id, new_state)
        else:
            # Retreat or cooled: persist state without notifying (re-arm).
            db.update_target_state(conn, t.target_id, new_state, None)
            log.debug("target %s -> %s (silent)", t.target_id, new_state)
    return notified
