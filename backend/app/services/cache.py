from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class _CacheEntry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: int = 1800, enabled: bool = True,
                 maxsize: int = 2000) -> None:
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled
        self._maxsize = maxsize
        self._items: dict[str, _CacheEntry[T]] = {}

    def get(self, key: str) -> T | None:
        if not self.enabled:
            return None

        entry = self._items.get(key)
        if entry is None:
            return None

        if entry.expires_at < time.time():
            self._items.pop(key, None)
            return None

        return entry.value

    def set(self, key: str, value: T) -> None:
        if not self.enabled:
            return
        now = time.time()
        # Evict expired entries first
        expired = [k for k, e in self._items.items() if e.expires_at < now]
        for k in expired:
            del self._items[k]
        # If still at capacity, drop the entry closest to expiry
        if len(self._items) >= self._maxsize:
            oldest = min(self._items, key=lambda k: self._items[k].expires_at)
            del self._items[oldest]
        self._items[key] = _CacheEntry(
            value=value,
            expires_at=now + self.ttl_seconds,
        )

