"""PDOK spatial service — fetches CBS administrative boundary geometries.

Data source
-----------
PDOK OGC API Features (OGC API - Features, Part 1: Core)
  https://api.pdok.nl/cbs/gebiedsindelingen/ogc/v1/

Collections used
----------------
  gemeente_gegeneraliseerd   → GM#### codes
  wijk_gegeneraliseerd       → WK###### codes
  buurt_gegeneraliseerd      → BU######## codes

⚠️ IMPORTANT: This PDOK endpoint does NOT support CQL/OGC filtering.
   The `filter` query parameter returns HTTP 400.
   All server-side filtering is therefore disabled; we filter in Python
   after fetching.  The full collection is cached for 24 h.

Property fields on each feature
---------------------------------
  statcode   — CBS region code, e.g. 'BU03440001'
  statnaam   — Region name, e.g. 'Lombok-West'
  gm_code    — Parent municipality code, e.g. 'GM0344'
  jaarcode   — Boundary year (integer), e.g. 2024
  jrstatcode — Year + statcode combined

Join key
--------
  feature.properties.statcode  ←→  CBS WijkenEnBuurten column (both stripped)
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import httpx

from cache import cache_get, cache_set, geometry_cache, make_key
from config import get_settings
import duckdb_client

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Collection registry ───────────────────────────────────────────────────────

_COLLECTION_MAP: dict[str, str] = {
    "gemeente": "gemeente_gegeneraliseerd",
    "wijk":     "wijk_gegeneraliseerd",
    "buurt":    "buurt_gegeneraliseerd",
}

_PAGE_LIMIT = 100      # PDOK max items per page (server rejects > 100)
_TIMEOUT    = 60.0     # seconds — geometry responses can be large

# ── Disk persistence ──────────────────────────────────────────────────────────
# Raw features (pre-year-filter) are stored as JSON files so PDOK only needs
# to be fetched ONCE ever — subsequent server restarts load from disk instantly.

_GEOM_DIR = Path(__file__).parent / "data" / "geometry"
_PROVINCE_MAP_PATH = _GEOM_DIR / "province_gm_map.json"

# Populated at startup via init_province_map()
_province_name_to_gm: dict[str, frozenset[str]] = {}


def _disk_path(geo_level: str) -> Path:
    return _GEOM_DIR / f"{geo_level}_raw.json"


def _load_from_disk(geo_level: str) -> list[dict] | None:
    path = _disk_path(geo_level)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.info("Loaded %d raw features for %s from disk cache", len(data), geo_level)
        return data
    except Exception as exc:
        logger.warning("Could not read disk cache for %s: %s", geo_level, exc)
        return None


def _save_to_disk(geo_level: str, features: list[dict]) -> None:
    try:
        _GEOM_DIR.mkdir(parents=True, exist_ok=True)
        _disk_path(geo_level).write_text(
            json.dumps(features, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Saved %d raw features for %s to disk", len(features), geo_level)
    except Exception as exc:
        logger.warning("Could not write disk cache for %s: %s", geo_level, exc)


# ── Province helpers ──────────────────────────────────────────────────────────

def _flatten_coords(geom: dict) -> list[tuple[float, float]]:
    """Collect all (lng, lat) coordinate pairs from any GeoJSON geometry."""
    coords: list[tuple[float, float]] = []
    def _walk(g: dict) -> None:
        t = g["type"]
        if t == "Point":
            coords.append(tuple(g["coordinates"][:2]))
        elif t in ("LineString", "MultiPoint"):
            coords.extend(tuple(c[:2]) for c in g["coordinates"])
        elif t in ("Polygon", "MultiLineString"):
            for ring in g["coordinates"]:
                coords.extend(tuple(c[:2]) for c in ring)
        elif t == "MultiPolygon":
            for poly in g["coordinates"]:
                for ring in poly:
                    coords.extend(tuple(c[:2]) for c in ring)
        elif t == "GeometryCollection":
            for sub in g.get("geometries", []):
                _walk(sub)
    _walk(geom)
    return coords


def _centroid(feature: dict) -> tuple[float, float]:
    pts = _flatten_coords(feature["geometry"])
    if not pts:
        return (0.0, 0.0)
    lng = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return (lng, lat)


def _point_in_ring(px: float, py: float, ring: list) -> bool:
    """Ray-casting point-in-polygon test for a single ring."""
    inside = False
    j = len(ring) - 1
    for i, ci in enumerate(ring):
        xi, yi = ci[0], ci[1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_in_geometry(px: float, py: float, geom: dict) -> bool:
    """Test whether (px, py) is inside a Polygon or MultiPolygon geometry."""
    t = geom["type"]
    if t == "Polygon":
        return _point_in_ring(px, py, geom["coordinates"][0])
    elif t == "MultiPolygon":
        return any(_point_in_ring(px, py, poly[0]) for poly in geom["coordinates"])
    return False


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in km between two WGS-84 lon/lat points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def _filter_by_buffer(
    features: list[dict],
    center_name_or_code: str,
    radius_km: float,
    geo_level: str = "gemeente",
) -> list[dict]:
    """Return features near a named/coded center region.

    Strategy (in priority order):
    1. Shared-boundary neighbors from cbs_spatial.duckdb (if available).
       Always includes the center itself.
    2. Haversine centroid-distance fallback (original behaviour).

    center_name_or_code: statnaam (e.g. 'Ede') or statcode (e.g. 'GM0228').
    Falls back to unfiltered if center is not found.
    """
    search_upper = center_name_or_code.strip().upper()
    search_lower = center_name_or_code.strip().lower()

    # Find the center feature first (needed for both strategies)
    center_feature: dict | None = None
    for f in features:
        props = f.get("properties", {})
        if (str(props.get("statcode", "")).strip().upper() == search_upper
                or str(props.get("statnaam", "")).strip().lower() == search_lower):
            center_feature = f
            break

    if center_feature is None:
        logger.warning(
            "Buffer center %r not found in %d features — showing unfiltered.",
            center_name_or_code, len(features),
        )
        return features

    center_statcode = str(center_feature.get("properties", {}).get("statcode", "")).strip()

    # ── Strategy 1: DuckDB shared-boundary neighbors ──────────────────────────
    neighbor_codes = duckdb_client.get_neighbors_local(center_statcode, geo_level)
    if neighbor_codes:
        # Include center + all direct neighbors
        neighbor_set = {c.upper() for c in neighbor_codes}
        neighbor_set.add(center_statcode.upper())

        # For a meaningful comparison: also include 2nd-degree neighbors when
        # the radius suggests a larger search area (>= 30 km for gemeente level)
        if radius_km >= 30 and geo_level == "gemeente":
            second_degree: set[str] = set()
            for nb in list(neighbor_set):
                for nb2 in duckdb_client.get_neighbors_local(nb, geo_level):
                    second_degree.add(nb2.upper())
            neighbor_set.update(second_degree)

        result = [
            f for f in features
            if str(f.get("properties", {}).get("statcode", "")).strip().upper() in neighbor_set
        ]
        logger.info(
            "Buffer (DuckDB neighbors) %r → %d/%d features (center=%s, 2nd-degree=%s)",
            center_name_or_code, len(result), len(features),
            center_statcode, "yes" if radius_km >= 30 else "no",
        )
        return result

    # ── Strategy 2: Haversine distance fallback ───────────────────────────────
    cx, cy = _centroid(center_feature)
    logger.info(
        "Buffer (haversine fallback) %r at (%.4f, %.4f), radius=%.1f km",
        center_name_or_code, cx, cy, radius_km,
    )

    result = [
        f for f in features
        if _haversine_km(cx, cy, *_centroid(f)) <= radius_km
    ]
    logger.info(
        "Buffer %r %.1f km → %d/%d features kept",
        center_name_or_code, radius_km, len(result), len(features),
    )
    return result


async def _build_province_gm_map() -> dict[str, frozenset[str]]:
    """Fetch province + gemeente geometries and compute province→GM containment map.

    Saved to disk so it only runs once ever.
    """
    global _province_name_to_gm

    # Load from disk cache if available
    if _PROVINCE_MAP_PATH.exists():
        try:
            raw = json.loads(_PROVINCE_MAP_PATH.read_text(encoding="utf-8"))
            result = {k: frozenset(v) for k, v in raw.items()}
            _province_name_to_gm = result
            logger.info("Loaded province→GM map from disk (%d provinces)", len(result))
            return result
        except Exception as exc:
            logger.warning("Could not read province map cache: %s", exc)

    logger.info("Building province→GM map via point-in-polygon …")

    # Fetch province geometry (small collection — 12 features)
    province_url = f"{settings.PDOK_OGC_BASE}/collections/provincie_gegeneraliseerd/items"
    province_features = await _fetch_all_pages(province_url)

    # Pick latest year for provinces
    year_features = _filter_by_year(province_features, settings.DEFAULT_GEO_YEAR)

    # Get gemeente centroids (use cached full gemeente collection)
    gem_cache_key = make_key("geom_full", "gemeente")
    gem_features = cache_get(geometry_cache, gem_cache_key) or _load_from_disk("gemeente")
    if gem_features is None:
        gem_features = await _fetch_all_pages(
            f"{settings.PDOK_OGC_BASE}/collections/gemeente_gegeneraliseerd/items"
        )
    gem_year = _filter_by_year(gem_features, settings.DEFAULT_GEO_YEAR)

    # Build mapping
    result: dict[str, list[str]] = {}
    for prov in year_features:
        pprops = prov.get("properties", {})
        pname: str = str(pprops.get("statnaam", "")).strip()
        pgeom = prov.get("geometry")
        if not pname or not pgeom:
            continue
        gm_codes: list[str] = []
        for gem in gem_year:
            gprops = gem.get("properties", {})
            statcode = str(gprops.get("statcode", "")).strip()
            geom = gem.get("geometry")
            if not statcode or not geom:
                continue
            cx, cy = _centroid(gem)
            if _point_in_geometry(cx, cy, pgeom):
                gm_codes.append(statcode)
        result[pname] = gm_codes
        logger.info("Province '%s' → %d gemeenten", pname, len(gm_codes))

    # Save to disk
    try:
        _GEOM_DIR.mkdir(parents=True, exist_ok=True)
        _PROVINCE_MAP_PATH.write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Province→GM map saved to disk")
    except Exception as exc:
        logger.warning("Could not save province map: %s", exc)

    frozen = {k: frozenset(v) for k, v in result.items()}
    _province_name_to_gm = frozen
    return frozen


async def init_province_map() -> None:
    """Public entry point — call at startup to populate the province→GM map."""
    await _build_province_gm_map()


def search_regions(query: str, limit: int = 12) -> list[dict]:
    """Search for regions by statnaam across gemeente/wijk/buurt caches.

    Returns a list of dicts: {statnaam, statcode, gm_code, level}.
    Sorted: exact prefix matches first, then alphabetical within each level.
    Only searches cached / disk-persisted collections — never blocks on PDOK.
    """
    if not query or len(query.strip()) < 2:
        return []

    q = query.strip().lower()
    results: list[dict] = []

    for level in ("gemeente", "wijk", "buurt"):
        full_cache_key = make_key("geom_full", level)
        features: list[dict] | None = cache_get(geometry_cache, full_cache_key)
        if features is None:
            features = _load_from_disk(level)
        if not features:
            continue

        year_features = _filter_by_year(features, settings.DEFAULT_GEO_YEAR)
        level_hits: list[dict] = []

        for f in year_features:
            props = f.get("properties", {})
            statnaam = str(props.get("statnaam", "")).strip()
            if not statnaam:
                continue
            if q in statnaam.lower():
                level_hits.append({
                    "statnaam": statnaam,
                    "statcode": str(props.get("statcode", "")).strip(),
                    "gm_code": str(props.get("gm_code", "")).strip(),
                    "level": level,
                })

        # Prefix matches first within each level
        level_hits.sort(key=lambda r: (0 if r["statnaam"].lower().startswith(q) else 1, r["statnaam"].lower()))
        results.extend(level_hits)

    return results[:limit]


# ── Main public API ───────────────────────────────────────────────────────────

async def get_geometries(
    geo_level: str,
    region_scope: str | None,
    year: int | None = None,
    province_scope: str | None = None,
    buffer_scope: str | None = None,
    buffer_km: float = 15.0,
) -> dict[str, Any]:
    """Fetch GeoJSON FeatureCollection from PDOK.

    The full collection for the geo_level is fetched and cached.
    Client-side filtering narrows it to region_scope when provided.

    Parameters
    ----------
    geo_level      : 'gemeente' | 'wijk' | 'buurt'
    region_scope   : GM#### code to narrow to one municipality, or None (all NL)
    year           : Preferred boundary year; latest used if None
    province_scope : Dutch province name to narrow gemeente results to that province
    buffer_scope   : Center region name or code for spatial buffer comparison
    buffer_km      : Buffer radius in km (default 15.0)

    Returns
    -------
    GeoJSON FeatureCollection with properties: statcode, statnaam, gm_code
    """
    collection = _COLLECTION_MAP.get(geo_level)
    if not collection:
        raise ValueError(
            f"Unknown geography level: {geo_level!r}. Use gemeente / wijk / buurt."
        )

    # Priority: 0) DuckDB local  1) in-memory cache  2) disk JSON  3) PDOK live fetch
    full_cache_key = make_key("geom_full", geo_level)

    # Fast path: local DuckDB geometry table (no disk I/O or PDOK call needed)
    features: list[dict] | None = duckdb_client.get_geometries_local(geo_level)
    if features is not None:
        logger.info("Geometry DuckDB HIT: %d %s features", len(features), geo_level)

    if features is None:
        features = cache_get(geometry_cache, full_cache_key)

    if features is None:
        # Try loading from disk first (persists across server restarts)
        features = _load_from_disk(geo_level)
        if features is not None:
            cache_set(geometry_cache, full_cache_key, features)
        else:
            logger.info(
                "Fetching full PDOK collection '%s' (no server-side filter supported) …",
                collection,
            )
            base_url = f"{settings.PDOK_OGC_BASE}/collections/{collection}/items"
            features = await _fetch_all_pages(base_url)
            # Persist to disk so next server restart skips PDOK entirely
            _save_to_disk(geo_level, features)
            cache_set(geometry_cache, full_cache_key, features)
            logger.info("Cached %d raw features for %s", len(features), geo_level)

    # Pick the right boundary year
    effective_year = year or settings.DEFAULT_GEO_YEAR
    year_features  = _filter_by_year(features, effective_year)

    # Province filter: narrow to municipalities within the named province
    if province_scope and geo_level == "gemeente" and _province_name_to_gm:
        pname = province_scope.strip()
        # Try exact match first, then case-insensitive
        gm_set = _province_name_to_gm.get(pname) or next(
            (v for k, v in _province_name_to_gm.items() if k.lower() == pname.lower()), None
        )
        if gm_set:
            year_features = [
                f for f in year_features
                if str(f.get("properties", {}).get("statcode", "")).strip().upper() in {c.upper() for c in gm_set}
            ]
            logger.info("Province filter '%s' → %d features", province_scope, len(year_features))
        else:
            logger.warning("Province '%s' not in province map — showing all", province_scope)

    # Buffer filter: narrow to features near the center region
    if buffer_scope:
        year_features = _filter_by_buffer(year_features, buffer_scope, buffer_km, geo_level)

    # Client-side scope filter
    # NOTE: province_scope is handled before calling this function (above)
    scoped = _filter_by_scope(year_features, geo_level, region_scope)

    if not scoped:
        logger.warning(
            "No PDOK features after filtering: level=%s scope=%s year=%s",
            geo_level, region_scope, effective_year,
        )

    geojson = _build_feature_collection(scoped)
    logger.info(
        "Returning %d PDOK features for level=%s scope=%s province=%s",
        len(scoped), geo_level, region_scope, province_scope,
    )
    return geojson


# ── Fetch helpers ─────────────────────────────────────────────────────────────

async def _fetch_all_pages(base_url: str) -> list[dict[str, Any]]:
    """Paginate through PDOK using OGC 'next' links and return all raw features.

    PDOK returns HTTP 400 for:
      - CQL filter parameters
      - Unknown query parameters (including 'offset')
    So we only send 'f' and 'limit' on the first request, then follow
    the 'next' link href verbatim from each response.
    """
    features: list[dict[str, Any]] = []
    next_url: str | None = base_url
    first = True

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        while next_url:
            try:
                if first:
                    resp = await client.get(
                        next_url, params={"f": "json", "limit": str(_PAGE_LIMIT)}
                    )
                    first = False
                else:
                    # Follow the href exactly as PDOK provided it
                    resp = await client.get(next_url)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "PDOK request failed HTTP %d: %s",
                    exc.response.status_code, next_url,
                )
                raise RuntimeError(
                    f"PDOK geometry fetch failed (HTTP {exc.response.status_code})"
                ) from exc

            batch = data.get("features", [])
            features.extend(batch)
            logger.debug(
                "PDOK page  got=%d  total_so_far=%d", len(batch), len(features)
            )

            # Find the 'next' link (OGC API Features standard)
            next_url = None
            for link in data.get("links", []):
                if link.get("rel") == "next":
                    next_url = link.get("href")
                    break

    return features


# ── Client-side filtering ─────────────────────────────────────────────────────

def _filter_by_year(features: list[dict], year: int) -> list[dict]:
    """Keep features with the requested jaarcode; fall back to latest available."""
    matched = [
        f for f in features
        if f.get("properties", {}).get("jaarcode") == year
    ]
    if matched:
        return matched

    # Fall back to the latest jaarcode present
    jaarcodes = [
        f["properties"]["jaarcode"]
        for f in features
        if f.get("properties", {}).get("jaarcode") is not None
    ]
    if not jaarcodes:
        return features   # no jaarcode info — return everything

    latest = max(jaarcodes)
    if latest != year:
        logger.warning(
            "Boundary year %d not available — using %d. "
            "Cross-year comparisons may not be valid.",
            year, latest,
        )
    return [f for f in features if f.get("properties", {}).get("jaarcode") == latest]


def _filter_by_scope(
    features: list[dict],
    geo_level: str,
    region_scope: str | None,
) -> list[dict]:
    """Filter features client-side by region_scope.

    - gemeente level + GM scope → single municipality by statcode
    - wijk / buurt level + GM scope → all regions whose gm_code matches
    - No scope → return all features
    """
    if region_scope is None:
        return features

    scope = region_scope.strip().upper()

    if geo_level == "gemeente" and scope.startswith("GM"):
        return [
            f for f in features
            if str(f.get("properties", {}).get("statcode", "")).strip().upper() == scope
        ]

    if geo_level in ("wijk", "buurt") and scope.startswith("GM"):
        return [
            f for f in features
            if str(f.get("properties", {}).get("gm_code", "")).strip().upper() == scope
        ]

    # WK scope for buurt: match on statcode prefix
    if geo_level == "buurt" and scope.startswith("WK"):
        return [
            f for f in features
            if str(f.get("properties", {}).get("statcode", "")).strip().upper()
               .startswith(scope[:8])
        ]

    return features


# ── Feature normalisation ─────────────────────────────────────────────────────

def _build_feature_collection(features: list[dict]) -> dict[str, Any]:
    """Build a clean GeoJSON FeatureCollection with only the fields we need."""
    clean: list[dict] = []
    for f in features:
        props   = f.get("properties") or {}
        statcode: str = str(props.get("statcode", "")).strip()
        statnaam: str = str(props.get("statnaam", "")).strip()
        gm_code:  str = str(props.get("gm_code",  "")).strip()
        geom = f.get("geometry")

        if not statcode or geom is None:
            continue

        clean.append({
            "type": "Feature",
            "properties": {
                "statcode": statcode,
                "statnaam": statnaam,
                "gm_code":  gm_code,
            },
            "geometry": geom,
        })

    return {"type": "FeatureCollection", "features": clean}
