"""OpenRouteService async client -- isochrones and routes.

Falls back to a Euclidean buffer when ORS is unavailable.
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

_PROFILES = {
    "walking":  "foot-walking",
    "foot":     "foot-walking",
    "cycling":  "cycling-regular",
    "bike":     "cycling-regular",
    "ebike":    "cycling-electric",
    "car":      "driving-car",
    "drive":    "driving-car",
    # pass-through for explicit ORS profile names
    "foot-walking":      "foot-walking",
    "cycling-regular":   "cycling-regular",
    "cycling-electric":  "cycling-electric",
    "driving-car":       "driving-car",
}

_DEMO_BASE  = "https://api.openrouteservice.org"


def _base_url() -> str:
    s = get_settings()
    return s.ORS_BASE_URL or _DEMO_BASE


def _headers() -> dict[str, str]:
    key = get_settings().ORS_API_KEY
    h: dict[str, str] = {
        "Content-Type": "application/json",
        # ORS isochrones returns GeoJSON -- must accept both
        "Accept": "application/json, application/geo+json",
    }
    if key:
        h["Authorization"] = key
    return h


def _resolve_profile(mode: str) -> str:
    return _PROFILES.get(mode.lower(), "foot-walking")


# -- Euclidean fallback (used when ORS is unavailable) -------------------------

# Approximate walking/cycling speeds for fallback buffer
_MODE_SPEED_KMH = {
    "foot-walking":      5.0,
    "cycling-regular":  15.0,
    "cycling-electric": 20.0,
    "driving-car":      40.0,
}

def _euclidean_isochrone(lon: float, lat: float, minutes: int, mode: str) -> dict[str, Any]:
    """Build a circular buffer approximating the travel-time isochrone.

    Uses average travel speed to convert time -> radius, then projects
    to a polygon on the WGS84 sphere. Not road-network accurate, but
    gives a useful visual when ORS is down.
    """
    speed_kmh = _MODE_SPEED_KMH.get(mode, 5.0)
    radius_km = (minutes / 60.0) * speed_kmh
    # 1 degree lat ~ 111 km; 1 degree lon ~ 111 km x cos(lat)
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(lat)))
    # 36-point circle
    n = 36
    coords = [
        [lon + dlon * math.cos(2 * math.pi * i / n),
         lat + dlat * math.sin(2 * math.pi * i / n)]
        for i in range(n)
    ]
    coords.append(coords[0])   # close ring
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [coords]},
        "properties": {
            "value":    minutes * 60,
            "center":   [lon, lat],
            "minutes":  minutes,
            "mode":     mode,
            "fallback": True,   # flag so UI can show a note
        },
    }


# -- Isochrone (with retry + fallback) -----------------------------------------

async def _ors_isochrone_raw(
    lon: float, lat: float, ranges_seconds: list[int], profile: str
) -> list[dict[str, Any]]:
    """Call ORS isochrones endpoint with 2 automatic retries on 5xx errors."""
    url = f"{_base_url()}/v2/isochrones/{profile}"
    body = {
        "locations":  [[lon, lat]],
        "range":      ranges_seconds,
        "range_type": "time",
        "smoothing":  0.25,
        "attributes": ["area"],
    }
    last_exc: Exception = RuntimeError("ORS not reached")
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(headers=_headers(), timeout=20.0) as client:
                resp = await client.post(url, json=body)
                if resp.status_code in (429, 502, 503, 504) and attempt < 2:
                    wait = 2 ** attempt   # 1s, 2s
                    logger.warning("ORS %s on attempt %d -- retrying in %ds", resp.status_code, attempt+1, wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                features = data.get("features", [])
                if features:
                    return features
                raise ValueError("ORS returned empty features")
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
        except Exception as exc:
            last_exc = exc
            break
    raise last_exc


async def get_isochrone(
    lon: float,
    lat: float,
    minutes: int,
    mode: str = "foot-walking",
) -> dict[str, Any]:
    """Fetch a single reachability polygon -- ORS with Euclidean fallback."""
    profile = _resolve_profile(mode)
    try:
        features = await _ors_isochrone_raw(lon, lat, [minutes * 60], profile)
    except Exception as exc:
        logger.warning("ORS unavailable (%s) -- using Euclidean fallback for %dmin %s", exc, minutes, mode)
        return _euclidean_isochrone(lon, lat, minutes, mode)

    feat = features[0]
    feat.setdefault("properties", {})
    feat["properties"]["center"]  = [lon, lat]
    feat["properties"]["minutes"] = minutes
    feat["properties"]["mode"]    = profile
    feat["properties"]["fallback"] = False
    return feat


async def get_multi_ring_isochrones(
    lon: float,
    lat: float,
    ring_minutes: list[int],
    mode: str = "foot-walking",
) -> list[dict[str, Any]]:
    """Fetch concentric isochrone rings -- ORS with Euclidean fallback.

    Returns cumulative polygons sorted ascending (smallest first).
    Each polygon represents the full area reachable in - N minutes.
    """
    profile = _resolve_profile(mode)
    ranges_seconds = sorted([m * 60 for m in ring_minutes], reverse=True)

    try:
        features = await _ors_isochrone_raw(lon, lat, ranges_seconds, profile)
        for feat in features:
            feat.setdefault("properties", {})
            feat["properties"]["center"]   = [lon, lat]
            feat["properties"]["minutes"]  = feat["properties"].get("value", 0) // 60
            feat["properties"]["mode"]     = profile
            feat["properties"]["fallback"] = False
        return sorted(features, key=lambda f: f["properties"].get("value", 0))

    except Exception as exc:
        logger.warning("ORS multi-ring unavailable (%s) -- using Euclidean fallback", exc)
        return [_euclidean_isochrone(lon, lat, m, mode) for m in sorted(ring_minutes)]


# -- Route ---------------------------------------------------------------------

async def get_route(
    origin_lon: float,
    origin_lat: float,
    dest_lon: float,
    dest_lat: float,
    mode: str = "foot-walking",
) -> dict[str, Any]:
    """Fetch turn-by-turn directions between two points.

    Returns a GeoJSON Feature (LineString) with properties:
        distance_m   -- total distance in metres
        duration_s   -- total duration in seconds
        mode         -- ORS profile used
    """
    profile = _resolve_profile(mode)
    url = f"{_base_url()}/v2/directions/{profile}/geojson"
    body = {
        "coordinates": [[origin_lon, origin_lat], [dest_lon, dest_lat]],
        "instructions": False,
    }

    async with httpx.AsyncClient(headers=_headers(), timeout=20.0) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

    features = data.get("features", [])
    if not features:
        raise ValueError(f"ORS returned no route between ({origin_lon},{origin_lat}) and ({dest_lon},{dest_lat})")

    feat = features[0]
    summary = feat.get("properties", {}).get("summary", {})
    feat["properties"]["distance_m"] = summary.get("distance", 0)
    feat["properties"]["duration_s"] = summary.get("duration", 0)
    feat["properties"]["mode"] = profile
    return feat
