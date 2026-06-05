"""Telegram notifier — two targets (plan §2 / decision §1 alerting).

  * log channel   — routine/near notices,
  * urgent channel — net-worth threshold breaches and target hits.

Telegram is OPTIONAL. With no bot token (or a missing chat id) the notifier
degrades to logging only, so the core never depends on it. Network/HTTP errors
are swallowed and logged — a failed notification must not abort an ingest run.
"""

from __future__ import annotations

import logging
from typing import Callable

import requests

import config

log = logging.getLogger("jagaimo.telegram")

API = "https://api.telegram.org/bot{token}/sendMessage"

# An HTTP poster maps (url, json_payload) -> None. Injectable for tests.
HttpPoster = Callable[[str, dict], None]


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str | None = None,
        log_chat_id: str | None = None,
        alert_chat_id: str | None = None,
        *,
        http: HttpPoster | None = None,
        timeout: float = 15.0,
    ) -> None:
        s = config.settings
        self.bot_token = bot_token if bot_token is not None else s.telegram_bot_token
        self.log_chat_id = (log_chat_id if log_chat_id is not None
                            else s.telegram_log_chat_id)
        self.alert_chat_id = (alert_chat_id if alert_chat_id is not None
                              else s.telegram_alert_chat_id)
        self.timeout = timeout
        self._http = http
        self._session = requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token)

    def _post(self, chat_id: str | None, text: str, channel: str) -> bool:
        if not self.enabled or not chat_id:
            log.info("[telegram:%s disabled] %s", channel, text)
            return False
        url = API.format(token=self.bot_token)
        payload = {"chat_id": chat_id, "text": text,
                   "parse_mode": "HTML", "disable_web_page_preview": True}
        try:
            if self._http is not None:
                self._http(url, payload)
            else:
                resp = self._session.post(url, json=payload, timeout=self.timeout)
                resp.raise_for_status()
            return True
        except Exception as exc:  # never abort a run on a notification failure
            log.warning("telegram %s send failed: %s", channel, exc)
            return False

    def send_log(self, text: str) -> bool:
        return self._post(self.log_chat_id, text, "log")

    def send_urgent(self, text: str) -> bool:
        return self._post(self.alert_chat_id, text, "urgent")
