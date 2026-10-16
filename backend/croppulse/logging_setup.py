"""Structured JSON logging with privacy-aware redaction.

Rules (tested in tests/security/test_logging_privacy.py):
  * Never log passwords, tokens, Authorization headers or secrets.
  * Never log precise coordinates in general-purpose logs: any float pair that
    looks like a lat/lon, and keys such as ``lat``/``lon``/``geometry``, are redacted.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

SENSITIVE_KEYS = {
    "password",
    "token",
    "access_token",
    "authorization",
    "secret",
    "secret_key",
    "earthdata_token",
    "geometry",
    "geometry_geojson",
    "coordinates",
    "lat",
    "lon",
    "latitude",
    "longitude",
    "centroid_lat",
    "centroid_lon",
    "email",
}

_TOKEN_RE = re.compile(r"v1\.[0-9a-f]{32}\.\d+\.[A-Za-z0-9_\-]+")
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")
# Decimal coordinates with >= 3 decimals (≈100 m precision or better)
_COORD_RE = re.compile(r"(?<![\w.])-?\d{1,3}\.\d{3,}(?![\w.])")
_URL_COORD_RE = re.compile(r"(?i)(lat(?:itude)?|lon(?:gitude)?)=[^&\s]+")


def redact_text(text: str) -> str:
    text = _TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _URL_COORD_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _COORD_RE.sub("[REDACTED_NUM]", text)
    return text


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if str(k).lower() in SENSITIVE_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, float):
        return round(value, 2)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
        }
        extra = getattr(record, "ctx", None)
        if isinstance(extra, dict):
            payload["ctx"] = redact(extra)
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_croppulse", False):
            root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._croppulse = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("httpx").setLevel("WARNING")


def log(logger: logging.Logger, level: int, msg: str, **ctx: Any) -> None:
    logger.log(level, msg, extra={"ctx": ctx})
