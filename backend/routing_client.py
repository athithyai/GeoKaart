"""OpenRouteService async client — isochrones and routes.

Supports:
  - Single isochrone: reachability polygon from a point in N minutes
  - Multi-ring isochrones: concentric bands at multiple time thresholds
  - Route: A → B directions as a GeoJSON LineString

Travel modes
------------
  foot-walking      pedestrian (default for station queries)
  cycling-regular   standard cycling
  cycling-electric  e-bike
  driving-car       car

API key
-------
  Set ORS_API_KEY in .env for the full free tier (2000 req/day).
  Without a key the public demo endpoint is used — rate-limited, dev only.
  Get a free key at: https://openrouteservice.org/dev/#/signup
"""
from __future__ import annotations

import logging
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
    h: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        h["Authorization"] = key
    return h


def _resolve_profile(mode: str) -> str:
    return _PROFILES.get(mode.lower(), "foot-walking")


# ── Isochrone ─────────────────────────────────────────────────────────────────

async def get_isochrone(
    lon: float,
    lat: float,
    minutes: int,
    mode: str = "foot-walking",
) -> dict[str, Any]:
    """Fetch a single reachability polygon from ORS.

    Returns a GeoJSON Feature (Polygon) with properties:
        value        — travel time in seconds
        center       — [lon, lat] of the origin point
        mode         — ORS profile used
    """
    profile = _resolve_profile(mode)
    url = f"{_base_url()}/v2/isochrones/{profile}"
    body = {
        "locations":  [[lon, lat]],
        "range":      [minutes * 60],        # ORS uses seconds
        "range_type": "time",
        "smoothing":  0.25,                  # slight smoothing — cleaner polygon
        "attributes": ["area"],
    }

    async with httpx.AsyncClient(headers=_headers(), timeout=20.0) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

    features = data.get("features", [])
    if not features:
        raise ValueError(f"ORS returned no isochrone for ({lon}, {lat}) at {minutes}min {mode}")

    feat = features[0]
    feat.setdefault("properties", {})
    feat["properties"]["center"] = [lon, lat]
    feat["properties"]["minutes"] = minutes
    feat["properties"]["mode"] = profile
    return feat


async def get_multi_ring_isochrones(
    lon: float,
    lat: float,
    ring_minutes: list[int],
    mode: str = "foot-walking",
) -> list[dict[str, Any]]:
    """Fetch concentric isochrone rings in a single ORS call.

    Returns a list of GeoJSON Features sorted by travel time ascending.
    Each feature represents the full reachable area up to that time threshold —
    use ring_to_bands() to convert to exclusive donut bands for rendering.

    Example: ring_minutes=[5, 10, 20] → three polygons:
        features[0] = area reachable in 5 min
        features[1] = area reachable in 10 min  (contains features[0])
        features[2] = area reachable in 20 min  (contains features[0] and [1])
    """
    profile = _resolve_profile(mode)
    url = f"{_base_url()}/v2/isochrones/{profile}"

    # ORS wants ranges in descending order, sorted ascending in response
    ranges_seconds = sorted([m * 60 for m in ring_minutes], reverse=True)

    body = {
        "locations":  [[lon, lat]],
        "range":      ranges_seconds,
        "range_type": "time",
        "smoothing":  0.25,
        "attributes": ["area"],
    }

    async with httpx.AsyncClient(headers=_headers(), timeout=30.0) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

    features = data.get("features", [])
    if not features:
        raise ValueError(f"ORS returned no rings for ({lon}, {lat}) {ring_minutes}min {mode}")

    for feat in features:
        feat.setdefault("properties", {})
        feat["properties"]["center"]  = [lon, lat]
        feat["properties"]["minutes"] = feat["properties"].get("value", 0) // 60
        feat["properties"]["mode"]    = profile

    # Sort smallest → largest
    return sorted(features, key=lambda f: f["properties"].get("value", 0))


# ── Route ─────────────────────────────────────────────────────────────────────

async def get_route(
    origin_lon: float,
    origin_lat: float,
    dest_lon: float,
    dest_lat: float,
    mode: str = "foot-walking",
) -> dict[str, Any]:
    """Fetch turn-by-turn directions between two points.

    Returns a GeoJSON Feature (LineString) with properties:
        distance_m   — total distance in metres
        duration_s   — total duration in seconds
        mode         — ORS profile used
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
