"""Lightweight geocoder using PDOK Locatieserver.

No API key required. Covers all Dutch addresses, stations, place names.
API docs: https://api.pdok.nl/bzk/locatieserver/search/v3_1/ui/
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.pdok.nl/bzk/locatieserver/search/v3_1"

# Well-known station coordinates — instant fallback, no API call needed
_STATION_COORDS: dict[str, tuple[float, float]] = {
    "rotterdam centraal":     (4.4683, 51.9246),
    "amsterdam centraal":     (4.9003, 52.3791),
    "utrecht centraal":       (5.1108, 52.0896),
    "den haag centraal":      (4.3231, 52.0802),
    "eindhoven":              (5.4803, 51.4427),
    "utrecht cs":             (5.1108, 52.0896),
    "amsterdam cs":           (4.9003, 52.3791),
    "rotterdam cs":           (4.4683, 51.9246),
    "den haag cs":            (4.3231, 52.0802),
    "amsterdam sloterdijk":   (4.8372, 52.3888),
    "amsterdam bijlmer":      (4.9475, 52.3125),
    "groningen":              (6.5665, 53.2128),
    "leiden centraal":        (4.4795, 52.1663),
    "delft":                  (4.3573, 52.0061),
    "haarlem":                (4.6383, 52.3874),
    "arnhem centraal":        (5.8991, 51.9849),
    "nijmegen":               (5.8532, 51.8430),
    "breda":                  (4.7783, 51.5957),
    "tilburg":                (5.0841, 51.5610),
    "maastricht":             (5.7074, 50.8512),
    "zwolle":                 (6.0919, 52.5056),
    "amersfoort centraal":    (5.3855, 52.1535),
    "almere centrum":         (5.2152, 52.3742),
}


async def geocode(query: str, n_results: int = 1) -> list[dict[str, Any]]:
    """Geocode a Dutch place name, address, or station.

    Returns a list of dicts with keys: name, lat, lon, type, statcode (optional).
    Falls back to station coordinate lookup before hitting the API.
    """
    normalised = query.lower().strip()

    # Fast path: well-known stations
    for key, (lon, lat) in _STATION_COORDS.items():
        if key in normalised or normalised in key:
            logger.info("Station fast-path: %s → (%s, %s)", query, lon, lat)
            return [{"name": query, "lon": lon, "lat": lat, "type": "station"}]

    # PDOK Locatieserver
    params = {
        "q":   query,
        "rows": n_results,
        "fl":  "id,weergavenaam,centroide_ll,type",
        "fq":  "bron:BAG OR bron:NWB OR bron:OSM OR type:gemeente OR type:woonplaats",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{_BASE}/free", params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("PDOK geocode failed for %r: %s", query, exc)
        return [{"error": str(exc), "lat": None, "lon": None}]

    docs = data.get("response", {}).get("docs", [])
    if not docs:
        logger.info("No geocode results for %r", query)
        return [{"error": "No results found", "lat": None, "lon": None}]

    results = []
    for doc in docs[:n_results]:
        centroid = doc.get("centroide_ll", "")  # "POINT(lon lat)"
        lon, lat = _parse_wkt_point(centroid)
        results.append({
            "name":     doc.get("weergavenaam", query),
            "lon":      lon,
            "lat":      lat,
            "type":     doc.get("type", "unknown"),
        })

    return results


def _parse_wkt_point(wkt: str) -> tuple[float | None, float | None]:
    """Parse 'POINT(4.4683 51.9246)' → (4.4683, 51.9246)."""
    try:
        inner = wkt.replace("POINT(", "").replace(")", "").strip()
        parts = inner.split()
        return float(parts[0]), float(parts[1])
    except Exception:
        return None, None
