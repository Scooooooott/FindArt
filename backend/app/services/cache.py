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
    def __init__(self, ttl_seconds: int = 1800, enabled: bool = True) -> None:
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled
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
        self._items[key] = _CacheEntry(
            value=value,
            expires_at=time.time() + self.ttl_seconds,
        )

