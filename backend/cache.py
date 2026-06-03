"""Shared in-memory cache using cachetools TTLCache.

All cache instances live here so services can share or invalidate them.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from cachetools import TTLCache

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Cache instances ───────────────────────────────────────────────────────────

# CBS catalog + DataProperties metadata
metadata_cache: TTLCache[str, Any] = TTLCache(
    maxsize=256,
    ttl=settings.CACHE_TTL_METADATA,
)

# PDOK geometry (GeoJSON FeatureCollections)
geometry_cache: TTLCache[str, Any] = TTLCache(
    maxsize=64,
    ttl=settings.CACHE_TTL_GEOMETRY,
)

# CBS observation DataFrames (serialised as list-of-dicts)
data_cache: TTLCache[str, Any] = TTLCache(
    maxsize=128,
    ttl=settings.CACHE_TTL_DATA,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_key(*parts: Any) -> str:
    """Create a stable cache key from arbitrary arguments."""
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def cache_get(store: TTLCache, key: str) -> Any | None:
    value = store.get(key)
    if value is not None:
        logger.debug("Cache HIT  key=%s", key)
    return value


def cache_set(store: TTLCache, key: str, value: Any) -> None:
    logger.debug("Cache MISS key=%s — storing", key)
    store[key] = value
