"""Logging setup for the core.

Human-readable by default; set `JAGAIMO_LOG_JSON=true` for one-line JSON records
(useful when shipping `ingest.log` to a collector). Call `setup_logging()` once
at process start (ingest / CLI entrypoints).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: int | str = logging.INFO) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    if os.getenv("JAGAIMO_LOG_JSON", "").lower() in {"1", "true", "yes"}:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"
        ))
    root.addHandler(handler)
    root.setLevel(level)
