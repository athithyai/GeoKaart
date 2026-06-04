"""Join engine — merges CBS statistical data with PDOK geometry.

The join key is:
    PDOK feature.properties.statcode  ←→  CBS DataFrame RegioS  (both stripped)

Output
------
An enriched GeoJSON FeatureCollection where every feature has:
    statcode      — region code
    statnaam      — region name
    value         — numeric CBS measure value (null if no match)
    label         — formatted display string (e.g. '42 356')

Plus FeatureCollection-level metadata:
    meta.measure_code   — column name used
    meta.period         — CBS period string
    meta.breaks         — list of class boundary values
    meta.colors         — list of hex color strings (len = n_classes)
    meta.null_color     — color for missing data
    meta.n_matched      — count of features with values
    meta.n_total        — total feature count
    meta.warnings       — list of warning strings
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── ColorBrewer sequential palettes (5-class and 7-class) ────────────────────

_PALETTES: dict[str, list[list[str]]] = {
    # Plasma — purple → magenta → orange → yellow. Best on dark maps.
    "Plasma": [
        ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
        ["#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c", "#5ec962", "#fde725"],
    ],
    # YlOrRd — yellow → orange → deep red. High contrast, intuitive for intensity.
    "YlOrRd": [
        ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],
        ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#f03b20", "#bd0026", "#800026"],
    ],
    # Magma — dark purple → orange → light yellow. Beautiful on dark maps.
    "Magma": [
        ["#000004", "#3b0f70", "#8c2981", "#de4968", "#fde0dd"],
        ["#000004", "#180f3d", "#440f76", "#7e2482", "#bd3786", "#ed6925", "#fcfdbf"],
    ],
    # Blues — light → dark blue. For water/density data on light maps.
    "Blues": [
        ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],
        ["#eff3ff", "#c6dbef", "#9ecae1", "#6baed6", "#3182bd", "#08519c", "#08306b"],
    ],
    # Greens — for environmental / land use data.
    "Greens": [
        ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"],
        ["#edf8e9", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#005a32"],
    ],
    # RdYlGn — red → yellow → green. Diverging: good for poverty / wealth comparisons.
    "RdYlGn": [
        ["#d7191c", "#fdae61", "#ffffbf", "#a6d96a", "#1a9641"],
        ["#d73027", "#f46d43", "#fdae61", "#fee08b", "#d9ef8b", "#a6d96a", "#1a9641"],
    ],
    # Brand (kept for backward compat) — but no longer default
    "Brand": [
        ["#e0f5fc", "#7dd4e8", "#00A1CD", "#1b3678", "#271D6C"],
        ["#e0f5fc", "#9de3f1", "#4dc4e0", "#00A1CD", "#0e5d9c", "#1b3678", "#271D6C"],
    ],
}

_NULL_COLOR = "#2d2d2d"          # dark grey — invisible gap on dark maps
_DEFAULT_PALETTE = "YlOrRd"     # warm yellow→red: pops on dark map, clear gradient


# ── Classification ────────────────────────────────────────────────────────────

def _quantile_breaks(values: np.ndarray, n: int) -> list[float]:
    """Compute quantile class breaks (n+1 boundaries for n classes)."""
    qs = np.linspace(0, 100, n + 1)
    return [float(np.percentile(values, q)) for q in qs]


def _equal_interval_breaks(values: np.ndarray, n: int) -> list[float]:
    mn, mx = float(values.min()), float(values.max())
    step = (mx - mn) / n
    return [mn + i * step for i in range(n + 1)]


def _jenks_breaks(values: np.ndarray, n: int) -> list[float]:
    """Fisher-Jenks natural breaks (simplified implementation)."""
    if len(values) <= n:
        return _equal_interval_breaks(values, n)

    sorted_v = np.sort(values)
    k = len(sorted_v)

    # Dynamic programming matrices
    mat1 = np.zeros((k + 1, n + 1))
    mat2 = np.full((k + 1, n + 1), np.inf)
    mat2[1, 1] = 0.0

    for j in range(2, k + 1):
        s1 = s2 = 0.0
        for i in range(1, j + 1):
            val = sorted_v[j - i - 1] if j - i - 1 >= 0 else sorted_v[0]
            s2 += val * val
            s1 += val
            w = float(i)
            v = s2 - (s1 * s1) / w
            i4 = j - i
            if i4 != 0:
                for l in range(2, n + 1):
                    if mat2[j][l] >= (v + mat2[i4][l - 1]):
                        mat1[j][l] = float(i4)
                        mat2[j][l] = v + mat2[i4][l - 1]
        mat1[j][1] = 1.0
        mat2[j][1] = s2 - (s1 * s1) / float(j)

    kclass = [0] * (n + 1)
    kclass[n] = k
    kclass[1] = 1

    for count_num in range(n, 1, -1):
        idx = int(mat1[kclass[count_num]][count_num]) - 1
        kclass[count_num - 1] = idx

    breaks = [float(sorted_v[kclass[i] - 1]) for i in range(1, n + 1)]
    breaks.insert(0, float(sorted_v[0]))
    return breaks


def _compute_breaks(values: np.ndarray, n_classes: int, method: str) -> list[float]:
    clean = values[~np.isnan(values)]
    if len(clean) == 0:
        return [0.0] * (n_classes + 1)
    if len(clean) == 1:
        v = float(clean[0])
        return [v] * (n_classes + 1)

    if method == "quantile":
        breaks = _quantile_breaks(clean, n_classes)
    elif method == "jenks":
        breaks = _jenks_breaks(clean, n_classes)
    else:
        breaks = _equal_interval_breaks(clean, n_classes)

    # De-duplicate breaks (can happen with heavily skewed data)
    unique: list[float] = []
    for b in breaks:
        if not unique or b > unique[-1]:
            unique.append(b)

    # Pad to expected length if de-duplication shortened
    while len(unique) < n_classes + 1:
        unique.append(unique[-1] + 1)

    return unique


def _assign_class(value: float, breaks: list[float]) -> int:
    """Return 0-based class index for a value given break boundaries."""
    n = len(breaks) - 1
    for i in range(n - 1, -1, -1):
        if value >= breaks[i]:
            return i
    return 0


def _format_value(v: float) -> str:
    """Format a number for display (thousands separator, limited decimals)."""
    if math.isnan(v):
        return "—"
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"{v:,.0f}".replace(",", "\u202f")  # narrow no-break space
    if v != int(v):
        return f"{v:.2f}"
    return str(int(v))


# ── Main public function ───────────────────────────────────────────────────────

def join_data_to_geometry(
    geojson: dict[str, Any],
    df: pd.DataFrame,
    measure_code: str,
    classification: str = "quantile",
    n_classes: int = 5,
    palette: str = _DEFAULT_PALETTE,
) -> tuple[dict[str, Any], list[str]]:
    """Merge CBS observations into PDOK GeoJSON features.

    Parameters
    ----------
    geojson        : PDOK GeoJSON FeatureCollection
    df             : CBS DataFrame with RegioS and measure_code columns
    measure_code   : Column to use as choropleth value
    classification : 'quantile' | 'jenks' | 'equal'
    n_classes      : Number of color classes (3–9)
    palette        : ColorBrewer palette name

    Returns
    -------
    (enriched_geojson, warnings)
    """
    warnings: list[str] = []
    features = geojson.get("features", [])

    if measure_code not in df.columns:
        warnings.append(f"Measure '{measure_code}' not found in CBS data.")
        return geojson, warnings

    # Build lookup: RegioS → value
    lookup: dict[str, float | None] = {}
    for _, row in df.iterrows():
        key = str(row.get("RegioS", "")).strip()
        raw = row.get(measure_code)
        lookup[key] = float(raw) if pd.notna(raw) else None

    # Collect valid numeric values for classification
    all_values = np.array([v for v in lookup.values() if v is not None], dtype=float)

    breaks = _compute_breaks(all_values, n_classes, classification)
    colors = _get_palette(palette, n_classes)

    period_values = df["Perioden"].dropna().unique().tolist() if "Perioden" in df.columns else []
    period_str = period_values[0] if period_values else ""

    # Enrich features
    matched = 0
    enriched: list[dict[str, Any]] = []
    for feat in features:
        props = dict(feat.get("properties") or {})
        statcode = str(props.get("statcode", "")).strip()
        value = lookup.get(statcode)

        if value is not None:
            cls_idx = _assign_class(value, breaks)
            color = colors[min(cls_idx, len(colors) - 1)]
            props["value"] = value
            props["label"] = _format_value(value)
            props["color"] = color
            matched += 1
        else:
            props["value"] = None
            props["label"] = "—"
            props["color"] = _NULL_COLOR

        enriched.append({**feat, "properties": props})

    if matched == 0:
        warnings.append(
            "No CBS regions matched the PDOK geometries. "
            "Check that geography_level and region_scope are consistent."
        )
    elif matched < len(features) * 0.5:
        unmatched = len(features) - matched
        warnings.append(f"{unmatched} of {len(features)} regions had no CBS data (shown in gray).")

    enriched_fc: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": enriched,
        "meta": {
            "measure_code": measure_code,
            "period": period_str,
            "breaks": breaks,
            "colors": colors,
            "null_color": _NULL_COLOR,
            "n_matched": matched,
            "n_total": len(features),
            "warnings": warnings,
        },
    }

    logger.info("Join complete: %d/%d features matched", matched, len(features))
    return enriched_fc, warnings


def _get_palette(name: str, n_classes: int) -> list[str]:
    """Return a ColorBrewer palette of the requested size."""
    palette_options = _PALETTES.get(name, _PALETTES[_DEFAULT_PALETTE])
    if n_classes <= 5:
        return palette_options[0][:n_classes]
    return palette_options[1][:n_classes]
