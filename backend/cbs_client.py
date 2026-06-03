"""CBS StatLine OData v3 HTTP client.

Key facts about CBS Kerncijfers Wijken en Buurten tables (86165NED etc.)
------------------------------------------------------------------------
- Geo column    : WijkenEnBuurten  (type GeoDetail in DataProperties)
- Period column : NONE — these are single-year cross-sectional snapshots.
                  The year is implicit in the table ID, not a queryable column.
- Measure types : TopicGroup / Topic

Responsibilities
----------------
- Auto-detect the geo column name per table via DataProperties
- Build correct $filter / $select params (no period filter for snapshot tables)
- Paginate and return a pandas DataFrame with normalised column names
- All network I/O is async (httpx.AsyncClient)
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx
import pandas as pd

from cache import cache_get, cache_set, data_cache, make_key, metadata_cache
from config import get_settings
import duckdb_client

logger = logging.getLogger(__name__)
settings = get_settings()

_PAGE_SIZE = 10_000


# ── Low-level fetch helpers ───────────────────────────────────────────────────

async def _get_json(
    client: httpx.AsyncClient, url: str, params: dict | None = None
) -> dict:
    """GET a URL and return parsed JSON, raising on HTTP errors."""
    resp = await client.get(url, params=params, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


async def _paginate(
    client: httpx.AsyncClient, base_url: str, params: dict
) -> list[dict]:
    """Collect all rows from a paginated OData endpoint."""
    rows: list[dict] = []
    skip = 0
    while True:
        p = {**params, "$top": _PAGE_SIZE, "$skip": skip, "$format": "json"}
        data = await _get_json(client, base_url, p)
        batch = data.get("value", [])
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        skip += _PAGE_SIZE
    return rows


# ── DataProperties inspection ─────────────────────────────────────────────────

async def get_data_properties(table_id: str) -> list[dict[str, Any]]:
    """Fetch DataProperties for a table — describes all available columns."""
    cache_key = make_key("data_properties", table_id)
    if cached := cache_get(metadata_cache, cache_key):
        return cached

    async with httpx.AsyncClient() as client:
        url = f"{settings.CBS_ODATA_BASE}/{table_id}/DataProperties"
        data = await _get_json(client, url, {"$format": "json"})
        props = data.get("value", [])

    cache_set(metadata_cache, cache_key, props)
    return props


async def _detect_geo_column(table_id: str) -> str:
    """Return the geographic dimension column name for a CBS table.

    CBS uses type 'GeoDetail' for the geo dimension in kerncijfers tables.
    The key is typically 'WijkenEnBuurten' for all kerncijfers tables.
    Falls back to 'WijkenEnBuurten' if detection fails.
    """
    cache_key = make_key("geo_col", table_id)
    if cached := cache_get(metadata_cache, cache_key):
        return cached

    try:
        props = await get_data_properties(table_id)
    except Exception as exc:
        logger.warning("Could not fetch DataProperties for %s: %s", table_id, exc)
        return "WijkenEnBuurten"

    geo_col: str | None = None
    for p in props:
        ptype = (p.get("Type") or "").lower()
        key: str = p.get("Key") or ""
        if not key:
            continue
        # CBS kerncijfers use 'GeoDetail' type for the geo dimension
        if ptype in ("geodetail", "geodimension", "geodetail"):
            geo_col = key
            break
        # Fallback: any Dimension whose key suggests geography
        if ptype == "dimension" and re.search(
            r"regio|wijk|buurt|gemeente|geo", key, re.IGNORECASE
        ):
            geo_col = key
            break

    geo_col = geo_col or "WijkenEnBuurten"
    logger.info("Table %s → geo_col=%s", table_id, geo_col)
    cache_set(metadata_cache, cache_key, geo_col)
    return geo_col


async def get_measure_columns(table_id: str) -> list[dict[str, str]]:
    """Return {code, title, unit} for numeric Topic/measure columns.

    Checks local DuckDB first (instant), falls back to CBS OData API.
    """
    local = duckdb_client.get_columns_local(table_id)
    if local is not None:
        logger.debug("Measure columns from DuckDB for %s (%d cols)", table_id, len(local))
        return local

    props = await get_data_properties(table_id)
    return [
        {
            "code": p["Key"],
            "title": p.get("Title", p["Key"]),
            "unit": p.get("Unit", ""),
        }
        for p in props
        if p.get("Type") in ("Topic", "TopicGroup") and p.get("Key")
    ]


# ── Region filter builder ─────────────────────────────────────────────────────

def _build_region_filter(
    geo_col: str, geography_level: str, region_scope: str | None
) -> str | None:
    """Build an OData $filter expression for the detected geo column.

    CBS region codes in WijkenEnBuurten are padded with spaces, e.g.:
      'GM0344    ' for Utrecht gemeente
      'WK034400  ' for a wijk in Utrecht
      'BU03440000' for a buurt
    """
    prefix_map = {"gemeente": "GM", "wijk": "WK", "buurt": "BU"}
    prefix = prefix_map.get(geography_level, "GM")

    if region_scope is None:
        # All regions at the requested level
        return f"startswith({geo_col},'{prefix}')"

    if geography_level == "gemeente" and region_scope.startswith("GM"):
        # Exact match (CBS pads codes with trailing spaces — startswith is safer)
        return f"startswith({geo_col},'{region_scope}')"

    if geography_level in ("wijk", "buurt") and region_scope.startswith("GM"):
        gm_digits = re.sub(r"[^0-9]", "", region_scope)
        sub_prefix = "WK" if geography_level == "wijk" else "BU"
        return f"startswith({geo_col},'{sub_prefix}{gm_digits}')"

    return f"startswith({geo_col},'{prefix}')"


# ── Main public API ───────────────────────────────────────────────────────────

async def get_observations(
    table_id: str,
    measure_code: str,
    geography_level: str,
    region_scope: str | None,
    period: str | None,  # kept for API compat but ignored — tables have no period dim
) -> pd.DataFrame:
    """Fetch observations from a CBS kerncijfers table.

    Parameters
    ----------
    table_id        : CBS table ID, e.g. '86165NED'
    measure_code    : Column name (Topic key), e.g. 'GemWOZWaardeWoning_65'
    geography_level : 'gemeente' | 'wijk' | 'buurt'
    region_scope    : GM#### code to narrow query, or None for all NL
    period          : Ignored — kerncijfers tables are single-year snapshots.

    Returns
    -------
    DataFrame with columns: RegioS (str), <measure_code> (float)
    'RegioS' is normalised from whatever the table's actual geo column is.
    """
    cache_key = make_key(
        "obs", table_id, measure_code, geography_level, region_scope
    )
    if cached := cache_get(data_cache, cache_key):
        logger.info("Cache HIT for %s/%s", table_id, measure_code)
        return pd.DataFrame(cached)

    # ── DuckDB fast paths ───────────────────────────────────────────────────
    # 1. Spatial DuckDB (wide-format, built by ingest.py) — preferred
    spatial_df = duckdb_client.get_observations_spatial(
        measure_code, geography_level, region_scope
    )
    if spatial_df is not None:
        cache_set(data_cache, cache_key, spatial_df.to_dict("records"))
        return spatial_df

    # 2. Legacy long-format DuckDB (cijfers.duckdb)
    local_df = duckdb_client.get_observations_local(
        table_id, measure_code, geography_level, region_scope
    )
    if local_df is not None:
        cache_set(data_cache, cache_key, local_df.to_dict("records"))
        return local_df
    # ────────────────────────────────────────────────────────────────────────

    geo_col = await _detect_geo_column(table_id)

    logger.info(
        "Fetching %s/%s  level=%s  scope=%s  geo_col=%s",
        table_id, measure_code, geography_level, region_scope, geo_col,
    )

    url = f"{settings.CBS_ODATA_BASE}/{table_id}/TypedDataSet"
    region_filter = _build_region_filter(geo_col, geography_level, region_scope)

    params: dict[str, Any] = {
        "$select": f"{geo_col},{measure_code}",
    }
    if region_filter:
        params["$filter"] = region_filter

    async with httpx.AsyncClient() as client:
        try:
            rows = await _paginate(client, url, params)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise ValueError(f"CBS table '{table_id}' not found.") from exc
            try:
                body = exc.response.json()
                msg = body.get("error", {}).get("message", str(exc))
            except Exception:
                msg = str(exc)
            raise ValueError(
                f"CBS API error for table '{table_id}' (HTTP {status}): {msg}"
            ) from exc

    if not rows:
        logger.warning("No rows for %s/%s scope=%s", table_id, measure_code, region_scope)
        return pd.DataFrame(columns=["RegioS", measure_code])

    df = pd.DataFrame(rows)

    # Normalise geo column → always "RegioS" for the join engine
    if geo_col in df.columns and geo_col != "RegioS":
        df = df.rename(columns={geo_col: "RegioS"})

    # Strip CBS padding spaces
    if "RegioS" in df.columns:
        df["RegioS"] = df["RegioS"].str.strip()

    # Coerce measure to numeric
    if measure_code in df.columns:
        df[measure_code] = pd.to_numeric(df[measure_code], errors="coerce")
        df = df.dropna(subset=[measure_code])

    cache_set(data_cache, cache_key, df.to_dict("records"))
    logger.info("Fetched %d rows for %s/%s", len(df), table_id, measure_code)
    return df
