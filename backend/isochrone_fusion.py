"""Isochrone × CBS statistics fusion engine.

Takes an isochrone polygon (or multiple rings) and CBS statistical data,
returns an enriched GeoJSON FeatureCollection of the intersecting regions
coloured by the CBS measure — clipped to the isochrone boundary.

Pipeline
--------
1. Load region geometries from disk cache (PDOK, already fetched)
2. Shapely spatial intersect: which regions overlap the isochrone?
3. Compute overlap fraction for weighted aggregation
4. Fetch CBS stats for the intersecting statcodes
5. Join stats to geometries, apply choropleth classification
6. Return enriched GeoJSON + ring summary table

Multi-ring support
------------------
For multi-ring queries (5min / 10min / 20min bands), each ring is processed
independently. Returns one FeatureCollection per ring plus a summary table
comparing stats across rings.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

import duckdb_client
import spatial_service
from join_engine import _compute_breaks as _classify, _format_value, _PALETTES, _assign_class, _get_palette, _DEFAULT_PALETTE as _JOIN_DEFAULT_PALETTE

logger = logging.getLogger(__name__)

_DEFAULT_PALETTE = _JOIN_DEFAULT_PALETTE   # "Brand"
_NULL_COLOR = "#D9D9D9"


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _isochrone_to_shapely(isochrone_feature: dict) -> Any:
    """Convert a GeoJSON Feature to a Shapely geometry."""
    return shape(isochrone_feature["geometry"])


def _intersect_regions(
    isochrone_geom,
    region_features: list[dict],
    min_overlap_fraction: float = 0.05,
) -> list[tuple[str, float, dict]]:
    """Return (statcode, overlap_fraction, feature) for regions that meaningfully overlap the isochrone."""
    results = []
    iso_area = isochrone_geom.area  # in degrees² — only used for ratios

    for feat in region_features:
        try:
            region_geom = shape(feat["geometry"])
        except Exception:
            continue

        if not isochrone_geom.intersects(region_geom):
            continue

        try:
            intersection = isochrone_geom.intersection(region_geom)
        except Exception:
            continue

        if intersection.is_empty:
            continue

        region_area = region_geom.area
        if region_area < 1e-12:
            continue

        overlap_fraction = intersection.area / region_area
        if overlap_fraction < min_overlap_fraction:
            continue

        statcode = feat.get("properties", {}).get("statcode", "")
        results.append((statcode, overlap_fraction, feat))

    return results


def _clip_geometry(region_geom, isochrone_geom) -> dict:
    """Return GeoJSON geometry clipped to the isochrone boundary."""
    try:
        clipped = region_geom.intersection(isochrone_geom)
        if clipped.is_empty:
            return mapping(region_geom)
        return mapping(clipped)
    except Exception:
        return mapping(region_geom)


# ── Choropleth helpers (mirrors join_engine logic) ────────────────────────────

def _build_choropleth(
    rows: list[dict],          # [{statcode, statnaam, value, overlap_fraction, clipped_geom}]
    measure_code: str,
    n_classes: int = 5,
    classification: str = "quantile",
    palette_name: str = _DEFAULT_PALETTE,
) -> dict:
    """Build an enriched GeoJSON FeatureCollection from intersection rows."""
    values = [r["value"] for r in rows if r["value"] is not None]

    if not values:
        return {"type": "FeatureCollection", "features": [], "meta": {"n_matched": 0, "n_total": len(rows)}}

    colors = _get_palette(palette_name, n_classes)
    n_classes = len(colors)

    breaks = _classify(np.array(values, dtype=float), n_classes, classification)
    if not breaks:
        breaks = [min(values), max(values)]

    features = []
    for r in rows:
        val = r["value"]
        if val is None:
            color = _NULL_COLOR
            label = "—"
        else:
            bucket = min(_assign_class(val, breaks), n_classes - 1)
            color = colors[bucket]
            label = _format_value(val)

        features.append({
            "type": "Feature",
            "geometry": r["clipped_geom"],
            "properties": {
                "statcode":        r["statcode"],
                "statnaam":        r["statnaam"],
                "value":           val,
                "label":           label,
                "color":           color,
                "overlap_fraction": round(r["overlap_fraction"], 3),
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "measure_code": measure_code,
            "breaks":       [round(b, 1) for b in breaks],
            "colors":       colors,
            "null_color":   _NULL_COLOR,
            "n_matched":    len([r for r in rows if r["value"] is not None]),
            "n_total":      len(rows),
        },
    }


# ── Main fusion function ───────────────────────────────────────────────────────

async def fuse_isochrone_stats(
    isochrone_feature: dict,
    stats_df: pd.DataFrame,
    geography_level: str,
    measure_code: str,
    n_classes: int = 5,
    classification: str = "quantile",
    min_overlap: float | None = None,
) -> dict:
    """Fuse an isochrone polygon with CBS stats into an enriched GeoJSON.

    Parameters
    ----------
    isochrone_feature : GeoJSON Feature (Polygon) from routing_client
    stats_df          : DataFrame with columns [RegioS|WijkenEnBuurten, <measure_code>]
    geography_level   : 'gemeente' | 'wijk' | 'buurt'
    measure_code      : CBS column name, used for choropleth legend

    Returns
    -------
    GeoJSON FeatureCollection with clipped region geometries coloured by value.
    """
    iso_geom = _isochrone_to_shapely(isochrone_feature)

    # Load cached region geometries (PDOK disk cache — instant after warmup)
    geojson = await spatial_service.get_geometries(geography_level, region_scope=None)
    region_features = geojson.get("features", []) if isinstance(geojson, dict) else []
    if not region_features:
        logger.warning("No region geometries available for level=%s", geography_level)
        return {"type": "FeatureCollection", "features": [], "meta": {}}

    # At gemeente level, the isochrone covers a tiny fraction of a large municipality —
    # lower the overlap threshold so any overlap counts.
    if min_overlap is None:
        min_overlap = 0.001 if geography_level == "gemeente" else 0.05

    # Spatial intersect
    intersecting = _intersect_regions(iso_geom, region_features, min_overlap_fraction=min_overlap)
    logger.info("Isochrone intersects %d %s regions", len(intersecting), geography_level)

    if not intersecting:
        return {"type": "FeatureCollection", "features": [], "meta": {"n_matched": 0, "n_total": 0}}

    # Build statcode → value lookup from the CBS DataFrame
    code_col = next((c for c in stats_df.columns if c in ("WijkenEnBuurten", "RegioS")), stats_df.columns[0])
    val_col  = next((c for c in stats_df.columns if c != code_col), None)

    stat_lookup: dict[str, float | None] = {}
    if val_col:
        for _, row in stats_df.iterrows():
            code = str(row[code_col]).strip()
            v = row[val_col]
            stat_lookup[code] = None if pd.isna(v) else float(v)

    # Build rows with clipped geometry
    rows = []
    for statcode, overlap_frac, feat in intersecting:
        region_geom = shape(feat["geometry"])
        clipped_geom = _clip_geometry(region_geom, iso_geom)
        statnaam = feat.get("properties", {}).get("statnaam", statcode)
        value = stat_lookup.get(statcode)

        rows.append({
            "statcode":         statcode,
            "statnaam":         statnaam,
            "value":            value,
            "overlap_fraction": overlap_frac,
            "clipped_geom":     clipped_geom,
        })

    return _build_choropleth(rows, measure_code, n_classes, classification)


# ── Multi-ring fusion ─────────────────────────────────────────────────────────

async def fuse_multi_ring_stats(
    ring_features: list[dict],   # sorted smallest → largest (from routing_client)
    stats_df: pd.DataFrame,
    geography_level: str,
    measure_code: str,
) -> dict:
    """Fuse multiple isochrone rings with CBS stats.

    Returns a combined GeoJSON where each region is assigned to the innermost
    ring it belongs to. Also returns a ring_summary table for the DataTable.
    """
    if not ring_features:
        return {"type": "FeatureCollection", "features": [], "meta": {}, "ring_summary": []}

    # Build shapely geometries for each ring (full cumulative polygons)
    ring_geoms = [_isochrone_to_shapely(f) for f in ring_features]

    # Get exclusive donut bands: ring[i] - ring[i-1]
    bands = []
    for i, (feat, geom) in enumerate(zip(ring_features, ring_geoms)):
        if i == 0:
            band_geom = geom
        else:
            try:
                band_geom = geom.difference(ring_geoms[i - 1])
            except Exception:
                band_geom = geom
        bands.append((feat["properties"].get("minutes", (i + 1) * 5), band_geom))

    # Load geometries once
    geojson = await spatial_service.get_geometries(geography_level, region_scope=None)
    region_features = geojson.get("features", []) if isinstance(geojson, dict) else []

    code_col = next((c for c in stats_df.columns if c in ("WijkenEnBuurten", "RegioS")), stats_df.columns[0])
    val_col  = next((c for c in stats_df.columns if c != code_col), None)
    stat_lookup: dict[str, float | None] = {}
    if val_col:
        for _, row in stats_df.iterrows():
            code = str(row[code_col]).strip()
            v = row[val_col]
            stat_lookup[code] = None if pd.isna(v) else float(v)

    all_rows = []
    ring_summary = []
    seen_codes: set[str] = set()

    # Use the largest ring's geom for overall palette
    largest_geom = ring_geoms[-1]

    for minutes, band_geom in bands:
        band_intersecting = _intersect_regions(band_geom, region_features)
        band_values = []

        for statcode, overlap_frac, feat in band_intersecting:
            if statcode in seen_codes:
                continue
            seen_codes.add(statcode)

            region_geom = shape(feat["geometry"])
            clipped_geom = _clip_geometry(region_geom, largest_geom)
            statnaam = feat.get("properties", {}).get("statnaam", statcode)
            value = stat_lookup.get(statcode)

            all_rows.append({
                "statcode":         statcode,
                "statnaam":         statnaam,
                "value":            value,
                "overlap_fraction": overlap_frac,
                "clipped_geom":     clipped_geom,
                "ring_minutes":     minutes,
            })
            if value is not None:
                band_values.append(value)

        ring_summary.append({
            "minutes":    minutes,
            "n_regions":  len(band_intersecting),
            "avg_value":  round(np.mean(band_values), 1) if band_values else None,
            "max_value":  round(np.max(band_values), 1) if band_values else None,
            "min_value":  round(np.min(band_values), 1) if band_values else None,
        })

    result = _build_choropleth(all_rows, measure_code)
    result["ring_summary"] = ring_summary
    result["ring_minutes"] = [m for m, _ in bands]

    return result
