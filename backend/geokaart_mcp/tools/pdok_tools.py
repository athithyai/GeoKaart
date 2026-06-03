"""MCP tools — PDOK spatial layer.

Wraps spatial_service (boundaries) and the PDOK Locatieserver (geocoding).

Tools
-----
pdok_get_boundaries  → GeoJSON FeatureCollection for gemeente/wijk/buurt
pdok_geocode         → free-text address or place name → {lat, lon, statcode, statnaam}
pdok_reverse_geocode → coordinates → nearest region
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from fastmcp import FastMCP

import spatial_service
import duckdb_client

logger = logging.getLogger(__name__)

mcp = FastMCP("GeoKaart PDOK Tools")

_LOCATIESERVER = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"


# ── Tool: get boundaries ───────────────────────────────────────────────────────

@mcp.tool(
    name="get_boundaries",
    description=(
        "Fetch administrative boundary GeoJSON from PDOK. "
        "Returns a GeoJSON FeatureCollection with statcode, statnaam, gm_code properties. "
        "Disk-cached after first fetch — subsequent calls are instant. "
        "Use region_scope (GM#### code) to return only sub-regions of one municipality."
    ),
)
async def pdok_get_boundaries(
    level: Annotated[str, "Geography level: 'gemeente', 'wijk', or 'buurt'"],
    region_scope: Annotated[str | None, "GM#### code to filter to one municipality, or null for all NL"] = None,
) -> dict:
    features = await spatial_service.get_geometries(level, region_scope)
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {"level": level, "scope": region_scope, "count": len(features)},
    }


# ── Tool: geocode ──────────────────────────────────────────────────────────────

@mcp.tool(
    name="geocode",
    description=(
        "Convert a Dutch address, place name, or municipality name to coordinates "
        "and the corresponding CBS region code. "
        "Uses PDOK Locatieserver (authoritative Dutch geocoder — no API key required). "
        "Examples: 'Amsterdam', 'Damrak 1 Amsterdam', 'Eindhoven station'."
    ),
)
async def pdok_geocode(
    query: Annotated[str, "Free-text address or place name to geocode"],
    n_results: Annotated[int, "Maximum number of results to return"] = 3,
) -> list[dict]:
    params = {
        "q": query,
        "rows": n_results,
        "fl": "id,weergavenaam,type,centroide_ll,gemeentecode,wijkcode,buurtcode",
        "fq": "type:(gemeente OR wijk OR buurt OR adres OR weg)",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(_LOCATIESERVER, params=params)
            resp.raise_for_status()
            docs = resp.json().get("response", {}).get("docs", [])
        except Exception as exc:
            logger.warning("PDOK geocode failed for %r: %s", query, exc)
            return [{"error": str(exc)}]

    results = []
    for doc in docs:
        centroid = doc.get("centroide_ll", "")
        lon, lat = None, None
        if centroid.startswith("POINT("):
            parts = centroid[6:-1].split()
            if len(parts) == 2:
                lon, lat = float(parts[0]), float(parts[1])

        # Resolve CBS code
        gm_code  = doc.get("gemeentecode")
        wk_code  = doc.get("wijkcode")
        bu_code  = doc.get("buurtcode")
        statcode = bu_code or wk_code or (f"GM{gm_code}" if gm_code else None)

        results.append({
            "name":     doc.get("weergavenaam", query),
            "type":     doc.get("type"),
            "lat":      lat,
            "lon":      lon,
            "statcode": statcode,
            "gm_code":  f"GM{gm_code}" if gm_code else None,
        })
    return results


# ── Tool: reverse geocode ──────────────────────────────────────────────────────

@mcp.tool(
    name="reverse_geocode",
    description=(
        "Convert WGS84 coordinates to the nearest Dutch administrative region. "
        "Returns statcode, statnaam, geography level, and parent municipality. "
        "Uses PDOK Locatieserver reverse geocoding."
    ),
)
async def pdok_reverse_geocode(
    lat: Annotated[float, "Latitude (WGS84), e.g. 52.3676"],
    lon: Annotated[float, "Longitude (WGS84), e.g. 4.9041"],
) -> dict:
    params = {
        "lat": lat,
        "lon": lon,
        "type": "buurt",
        "fl": "id,weergavenaam,gemeentecode,wijkcode,buurtcode",
        "rows": 1,
    }
    _reverse_url = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/reverse"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(_reverse_url, params=params)
            resp.raise_for_status()
            docs = resp.json().get("response", {}).get("docs", [])
        except Exception as exc:
            logger.warning("PDOK reverse geocode failed for (%s, %s): %s", lat, lon, exc)
            return {"error": str(exc)}

    if not docs:
        return {"error": "No region found at those coordinates."}

    doc = docs[0]
    gm_code  = doc.get("gemeentecode")
    wk_code  = doc.get("wijkcode")
    bu_code  = doc.get("buurtcode")
    statcode = bu_code or wk_code or (f"GM{gm_code}" if gm_code else None)

    info = duckdb_client.get_region_info(statcode) if statcode else None
    return {
        "name":     doc.get("weergavenaam"),
        "statcode": statcode,
        "gm_code":  f"GM{gm_code}" if gm_code else None,
        "statnaam": info.get("statnaam") if info else None,
        "level":    "buurt" if bu_code else "wijk" if wk_code else "gemeente",
    }
