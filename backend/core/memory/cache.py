import time
import hashlib
import re
from typing import Any


class FACTCache:
    def __init__(self, default_ttl: int = 60, static_ttl: int = 3600):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl
        self._static_ttl = static_ttl

        self._static_patterns = [
            re.compile(r"^what('s| is) (your )?name", re.I),
            re.compile(r"^who are you", re.I),
            re.compile(r"^what can you do", re.I),
            re.compile(r"^help$", re.I),
        ]

    def _make_key(self, text: str) -> str:
        normalized = text.lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def get(self, text: str) -> Any | None:
        key = self._make_key(text)
        return self._get_by_key(key)

    def get_key(self, key: str) -> Any | None:
        """Get cached value by explicit key (no hashing)."""
        return self._get_by_key(key)

    def set_key(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set cached value by explicit key (no hashing).
        Useful for composite keys like 'session_id:query'.
        """
        if ttl is None:
            ttl = self._default_ttl
        self._cache[key] = (value, time.time() + ttl)

    def _get_by_key(self, key: str) -> Any | None:
        if key in self._cache:
            value, expires_at = self._cache[key]
            if time.time() < expires_at:
                return value
            del self._cache[key]
        return None

    def set(self, text: str, value: Any) -> None:
        key = self._make_key(text)
        is_static = any(p.search(text) for p in self._static_patterns)
        ttl = self._static_ttl if is_static else self._default_ttl
        self._cache[key] = (value, time.time() + ttl)

    def invalidate(self, text: str) -> None:
        key = self._make_key(text)
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()
