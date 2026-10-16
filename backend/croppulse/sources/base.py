"""Shared adapter infrastructure: HTTP with retries, raw-response caching, typed errors."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from croppulse.config import get_settings
from croppulse.logging_setup import log

logger = logging.getLogger(__name__)


class SourceError(Exception):
    """Base class: the source could not provide usable data. Never replaced by fake data."""


class SourceNotConfigured(SourceError):
    pass


class SourceUnavailable(SourceError):
    pass


class SourceSchemaError(SourceError):
    """Response did not match the expected schema (possible upstream change)."""


@dataclass
class RawResponse:
    payload: Any
    url: str
    retrieved_at: datetime
    cache_path: Path | None
    from_cache: bool


class Transport(Protocol):
    def get(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> httpx.Response: ...


# Test hook: when set, every HttpFetcher uses this transport instead of a real HTTP client.
default_transport: Transport | None = None


class HttpFetcher:
    """GET JSON with timeouts, bounded exponential backoff and an on-disk raw cache.

    The cache key is the full request (URL + sorted params). Cached raw responses are
    the reproducible source reference stored on every derived record (``raw_ref``).
    """

    def __init__(self, source_id: str, transport: Transport | None = None, cache_dir: Path | None = None) -> None:
        s = get_settings()
        self.source_id = source_id
        self.client: Transport = transport or default_transport or httpx.Client(timeout=s.http_timeout_seconds, follow_redirects=True)  # type: ignore[assignment]
        self.max_retries = s.http_max_retries
        self.cache_dir = cache_dir or (s.data_dir / "raw" / source_id)

    def _key(self, url: str, params: dict[str, Any]) -> str:
        canon = url + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        return hashlib.sha256(canon.encode()).hexdigest()[:24]

    def get_json(self, url: str, params: dict[str, Any], *, use_cache: bool = True, cacheable: bool = True) -> RawResponse:
        key = self._key(url, params)
        path = self.cache_dir / f"{key}.json"
        if use_cache and path.exists():
            blob = json.loads(path.read_text())
            return RawResponse(blob["payload"], blob["url"], datetime.fromisoformat(blob["retrieved_at"]), path, True)

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self.client.get(url, params=params, headers={"Accept": "application/json"})
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise SourceUnavailable(f"HTTP {resp.status_code} from {self.source_id}")
                if resp.status_code in (401, 403):
                    raise SourceNotConfigured(f"HTTP {resp.status_code}: authentication/authorisation required")
                if resp.status_code >= 400:
                    raise SourceSchemaError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                payload = resp.json()
                retrieved = datetime.now(UTC)
                if cacheable:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(".tmp")
                    tmp.write_text(json.dumps({"url": url, "params": params, "retrieved_at": retrieved.isoformat(), "payload": payload}))
                    tmp.replace(path)
                return RawResponse(payload, url, retrieved, path if cacheable else None, False)
            except (SourceNotConfigured, SourceSchemaError):
                raise
            except (httpx.HTTPError, SourceUnavailable, ValueError) as exc:
                last_exc = exc
                log(logger, logging.WARNING, "source request failed", source=self.source_id, attempt=attempt + 1, error=str(exc)[:200])
                if attempt + 1 < self.max_retries:
                    time.sleep(min(2**attempt, 8))
        raise SourceUnavailable(f"{self.source_id} unavailable after {self.max_retries} attempts: {last_exc}")


def relpath(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(get_settings().data_dir))
    except ValueError:
        return str(path)
