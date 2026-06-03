"""Tests for join_engine.py — CBS data + PDOK geometry merge."""
from __future__ import annotations

import pandas as pd
import pytest

from join_engine import _compute_breaks, _format_value, join_data_to_geometry


# ── Test fixtures ─────────────────────────────────────────────────────────────

def make_geojson(statcodes: list[str]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"statcode": code, "statnaam": f"Region {code}"},
                "geometry": {"type": "Point", "coordinates": [5.0, 52.0]},
            }
            for code in statcodes
        ],
    }


def make_df(statcodes: list[str], values: list[float], measure: str = "Bevolking_1") -> pd.DataFrame:
    return pd.DataFrame({
        "RegioS": statcodes,
        "Perioden": ["2024JJ00"] * len(statcodes),
        measure: values,
    })


# ── Full match ────────────────────────────────────────────────────────────────

def test_join_full_match():
    codes = ["GM0363", "GM0599", "GM0344"]
    values = [921000.0, 651000.0, 361000.0]

    geojson = make_geojson(codes)
    df = make_df(codes, values)

    result, warnings = join_data_to_geometry(geojson, df, "Bevolking_1")

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 3
    assert result["meta"]["n_matched"] == 3
    assert result["meta"]["n_total"] == 3
    assert not warnings

    for feat in result["features"]:
        assert feat["properties"]["value"] is not None
        assert feat["properties"]["color"] != "#cccccc"


# ── Partial match ─────────────────────────────────────────────────────────────

def test_join_partial_match():
    geojson_codes = ["GM0363", "GM0599", "GM0344", "GM9999"]  # GM9999 has no CBS data
    df_codes = ["GM0363", "GM0599", "GM0344"]

    geojson = make_geojson(geojson_codes)
    df = make_df(df_codes, [100.0, 200.0, 300.0])

    result, warnings = join_data_to_geometry(geojson, df, "Bevolking_1")

    matched_features = [f for f in result["features"] if f["properties"]["value"] is not None]
    null_features = [f for f in result["features"] if f["properties"]["value"] is None]

    assert len(matched_features) == 3
    assert len(null_features) == 1
    assert null_features[0]["properties"]["color"] == "#cccccc"
    assert result["meta"]["n_matched"] == 3


# ── Zero matches warning ──────────────────────────────────────────────────────

def test_join_no_match_produces_warning():
    geojson = make_geojson(["GM0001", "GM0002"])
    df = make_df(["WK000100", "WK000200"], [10.0, 20.0])  # wrong codes

    _, warnings = join_data_to_geometry(geojson, df, "Bevolking_1")
    assert any("No CBS regions matched" in w for w in warnings)


# ── Missing measure column ────────────────────────────────────────────────────

def test_join_missing_measure():
    geojson = make_geojson(["GM0363"])
    df = make_df(["GM0363"], [100.0], measure="Bevolking_1")

    _, warnings = join_data_to_geometry(geojson, df, "NONEXISTENT_COLUMN")
    assert any("not found" in w for w in warnings)


# ── Color breaks ──────────────────────────────────────────────────────────────

def test_quantile_breaks_count():
    import numpy as np
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    breaks = _compute_breaks(values, 5, "quantile")
    assert len(breaks) == 6  # n_classes + 1 boundaries


def test_equal_interval_breaks():
    import numpy as np
    values = np.array([0.0, 100.0])
    breaks = _compute_breaks(values, 5, "equal")
    assert len(breaks) == 6
    assert abs(breaks[-1] - 100.0) < 1e-9


def test_breaks_monotone():
    import numpy as np
    values = np.arange(1.0, 101.0)
    for method in ("quantile", "equal", "jenks"):
        breaks = _compute_breaks(values, 5, method)
        for i in range(len(breaks) - 1):
            assert breaks[i] <= breaks[i + 1], f"Non-monotone breaks for {method}: {breaks}"


# ── GeoJSON structure ─────────────────────────────────────────────────────────

def test_output_is_valid_feature_collection():
    geojson = make_geojson(["GM0363"])
    df = make_df(["GM0363"], [500.0])

    result, _ = join_data_to_geometry(geojson, df, "Bevolking_1")

    assert result["type"] == "FeatureCollection"
    assert "features" in result
    assert "meta" in result
    assert "breaks" in result["meta"]
    assert "colors" in result["meta"]

    feat = result["features"][0]
    assert feat["type"] == "Feature"
    assert "properties" in feat
    assert "geometry" in feat
    assert "value" in feat["properties"]
    assert "label" in feat["properties"]
    assert "color" in feat["properties"]


# ── Format value ──────────────────────────────────────────────────────────────

def test_format_value_large_number():
    assert "," in _format_value(1_234_567) or "\u202f" in _format_value(1_234_567) or "M" in _format_value(1_234_567)


def test_format_value_small_decimal():
    result = _format_value(3.14)
    assert "3.14" in result


def test_format_value_nan():
    import math
    assert "—" in _format_value(float("nan"))
