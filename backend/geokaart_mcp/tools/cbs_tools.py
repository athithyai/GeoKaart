"""MCP tools — CBS StatLine data layer.

Wraps existing cbs_client, duckdb_client, and catalog_index so any MCP-compatible
client (Claude Desktop, Cursor, the GeoKaart orchestrator) can call them directly.

Tools
-----
cbs_search_catalog   → discover available tables/measures for a topic
cbs_get_measures     → list all measure columns in a CBS table
cbs_get_stats        → fetch one measure for a region (DuckDB-first, OData fallback)
cbs_get_neighbors    → find administratively adjacent regions
cbs_get_region_info  → metadata about a region code
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated

# Allow imports from backend/ root when the MCP server runs standalone
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from fastmcp import FastMCP

import duckdb_client
import cbs_client as _cbs
from catalog_index import CatalogIndex, _PRIORITY_TABLES

logger = logging.getLogger(__name__)

mcp = FastMCP("GeoKaart CBS Tools")

# Module-level catalog — built lazily on first call
_catalog: CatalogIndex | None = None


async def _get_catalog() -> CatalogIndex:
    global _catalog
    if _catalog is None:
        _catalog = await CatalogIndex.build()
    return _catalog


# ── Tool: search catalog ───────────────────────────────────────────────────────

@mcp.tool(
    name="search_catalog",
    description=(
        "Search the CBS StatLine catalog for tables and measure codes matching a topic. "
        "Returns table IDs, titles, and example measure codes. "
        "Use this before calling cbs_get_stats when you don't know the table_id or measure_code."
    ),
)
async def cbs_search_catalog(
    topic: Annotated[str, "Keyword to search, e.g. 'income', 'housing', 'energy', 'population'"],
    geo_level: Annotated[str, "Geography level: 'gemeente', 'wijk', or 'buurt'"] = "gemeente",
) -> list[dict]:
    cat = await _get_catalog()
    results = []
    for tbl in cat.list_tables():
        score = (
            (topic.lower() in tbl.title.lower()) +
            any(topic.lower() in kw for kw in tbl.title.lower().split())
        )
        if score > 0:
            measures = cat.get_measures(tbl.id)[:5]  # top 5 measures as hints
            results.append({
                "table_id": tbl.id,
                "title": tbl.title,
                "period": tbl.period,
                "geo_levels": tbl.geo_levels,
                "example_measures": [m["key"] for m in measures],
            })
    # Also try the semantic find_table method
    try:
        best_id = cat.find_table(topic, geo_level)
        if best_id and not any(r["table_id"] == best_id for r in results):
            measures = cat.get_measures(best_id)[:5]
            results.insert(0, {
                "table_id": best_id,
                "title": f"Best match for '{topic}'",
                "period": "auto",
                "geo_levels": [geo_level],
                "example_measures": [m["key"] for m in measures],
            })
    except Exception:
        pass
    return results[:10]


# ── Tool: get measures ─────────────────────────────────────────────────────────

@mcp.tool(
    name="get_measures",
    description=(
        "List all available measure columns in a CBS table. "
        "Returns the measure code (use as measure_code in cbs_get_stats), title, and unit. "
        "Priority tables: 86165NED (2025 demographics/housing), 85984NED (2024 full)."
    ),
)
async def cbs_get_measures(
    table_id: Annotated[str, "CBS table ID, e.g. '86165NED'"],
) -> list[dict]:
    # Try DuckDB first (instant)
    local = duckdb_client.get_columns_local(table_id)
    if local:
        return local

    # Fall back to CBS OData DataProperties
    cols = await _cbs.get_measure_columns(table_id)
    return cols


# ── Tool: get stats ────────────────────────────────────────────────────────────

@mcp.tool(
    name="get_stats",
    description=(
        "Fetch a CBS statistical measure for Dutch administrative regions. "
        "Returns a list of {statcode, statnaam, value, label} records. "
        "DuckDB cache is checked first; falls back to live CBS OData API. "
        "Set region_scope to a GM#### code to restrict to one municipality's sub-regions."
    ),
)
async def cbs_get_stats(
    table_id: Annotated[str, "CBS table ID, e.g. '86165NED'"],
    measure_code: Annotated[str, "CBS column name, e.g. 'AantalInwoners_5'"],
    geography_level: Annotated[str, "One of: 'gemeente', 'wijk', 'buurt'"] = "gemeente",
    region_scope: Annotated[str | None, "GM#### code to restrict to one municipality, or null for all NL"] = None,
    top_n: Annotated[int, "Return only the top N regions by value (0 = all)"] = 0,
) -> list[dict]:
    # DuckDB-first path
    df: pd.DataFrame | None = duckdb_client.get_observations_local(
        table_id, measure_code, geography_level, region_scope
    )

    if df is None or df.empty:
        # OData fallback
        try:
            df = await _cbs.get_observations(
                table_id, measure_code, geography_level, region_scope, period=None
            )
        except Exception as exc:
            logger.warning("CBS OData failed for %s/%s: %s", table_id, measure_code, exc)
            return []

    if df is None or df.empty:
        return []

    # Normalise column names — DuckDB returns WijkenEnBuurten, OData returns RegioS
    code_col = next((c for c in df.columns if c in ("WijkenEnBuurten", "RegioS")), df.columns[0])
    val_col  = next((c for c in df.columns if c != code_col), None)

    rows = []
    for _, row in df.iterrows():
        val = row.get(val_col) if val_col else None
        if pd.isna(val) if val is not None else True:
            val = None
        code = str(row[code_col]).strip()
        # Attempt a name lookup
        info = duckdb_client.get_region_info(code)
        name = info.get("statnaam", code) if info else code
        label = (
            f"{val:,.0f}".replace(",", " ") if isinstance(val, float) and val == int(val)
            else f"{val:.1f}" if isinstance(val, float) else str(val) if val is not None else "—"
        )
        rows.append({"statcode": code, "statnaam": name, "value": val, "label": label})

    rows = [r for r in rows if r["value"] is not None]
    rows.sort(key=lambda r: r["value"], reverse=True)

    if top_n > 0:
        rows = rows[:top_n]

    return rows


# ── Tool: get neighbors ────────────────────────────────────────────────────────

@mcp.tool(
    name="get_neighbors",
    description=(
        "Return all administratively adjacent regions that share a border with the given region. "
        "Uses the pre-computed ST_Touches adjacency table in cbs_spatial.duckdb."
    ),
)
async def cbs_get_neighbors(
    statcode: Annotated[str, "CBS region code, e.g. 'GM0363' (Amsterdam) or 'BU03440001'"],
    level: Annotated[str, "Geography level: 'gemeente', 'wijk', or 'buurt'"] = "gemeente",
) -> list[dict]:
    codes = duckdb_client.get_neighbors_local(statcode, level)
    results = []
    for code in codes:
        info = duckdb_client.get_region_info(code)
        results.append({
            "statcode": code,
            "statnaam": info.get("statnaam", code) if info else code,
        })
    return results


# ── Tool: get region info ──────────────────────────────────────────────────────

@mcp.tool(
    name="get_region_info",
    description=(
        "Look up metadata for a CBS region code: name, geography level, parent municipality. "
        "Useful for resolving a name to a code before calling other tools."
    ),
)
async def cbs_get_region_info(
    statcode: Annotated[str, "CBS region code, e.g. 'GM0363', 'WK036300', 'BU03630000'"],
) -> dict:
    info = duckdb_client.get_region_info(statcode)
    if info is None:
        return {"error": f"Region '{statcode}' not found in local database."}
    return info
