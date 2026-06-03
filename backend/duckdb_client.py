"""DuckDB-backed local query layer for CBS regional statistics.

Two databases
-------------
cijfers.duckdb
    Long-format CBS bulk CSV data (legacy, still used for fast OData fallback).
    Measure (CSV Identifier) | WijkenEnBuurten | Value

cbs_spatial.duckdb
    Wide-format preprocessed data built by ``ingest.run_ingest()``.
    Tables: regions, neighbors, stats_gemeente, stats_wijk, stats_buurt, ingest_log.

This module translates between two code systems:
- CSV Identifiers : used in the DuckDB table   (e.g. 'T001036')
- OData codes     : used by the LLM / planner  (e.g. 'AantalInwoners_5')

Translation is done via:
1. Static lookup table _ODATA_TO_CSV (covers known working codes)
2. Title matching against the cbs_<tbl>_measures table stored in DuckDB

When data is not available locally, returns None → cbs_client falls back to OData.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_DB_PATH         = Path(__file__).parent / "data" / "cijfers.duckdb"
_SPATIAL_DB_PATH = Path(__file__).parent / "data" / "cbs_spatial.duckdb"
_GEO_DB_PATH     = Path(__file__).parent / "data" / "gemeente_geo.duckdb"

# Singleton read-only connections
_conn: duckdb.DuckDBPyConnection | None = None
_spatial_conn: duckdb.DuckDBPyConnection | None = None
_geo_conn: duckdb.DuckDBPyConnection | None = None  # spatial ext loaded, for geometry queries


# ── Static OData → CSV Identifier mapping ─────────────────────────────────────
# Maps OData measure codes (used by the LLM planner) to CBS CSV Identifiers
# (used in the DuckDB long-format table).
#
# CBS kerncijfers tables:
#   86165NED = 2025 edition — has: demographics, housing, vehicles, area
#   85984NED = 2024 edition — has: all of the above PLUS energy, labor, income,
#                                   social security, care, business, education, proximity
#
# OData codes on left, CBS CSV MeasureCodes.Identifier on right.
_ODATA_TO_CSV: dict[str, str] = {

    # ── Bevolking — 86165NED (2025) and 85984NED (2024) ───────────────────
    "AantalInwoners_5":          "T001036",   # Aantal inwoners
    "Bevolkingsdichtheid_34":    "M000100",   # Bevolkingsdichtheid
    "Mannen_6":                  "3000",      # Mannen
    "Vrouwen_7":                 "4000",      # Vrouwen
    "k_0Tot15Jaar_8":            "10680",     # 0 tot 15 jaar
    "k_65JaarOfOuder_12":        "80200",     # 65 jaar of ouder
    # 85984NED (2024) bevolking codes
    "GeboorteTotaal_25":         "M000173_1", # Geboorte totaal
    "SterfteTotaal_27":          "M000179_1", # Sterfte totaal
    "HuishoudensTotaal_29":      "1050010_2", # Huishoudens totaal

    # ── Wonen en vastgoed — 86165NED (2025) and 85984NED (2024) ───────────
    "GemiddeldeWOZWaardeVanWoningen_39": "M001642",    # Gem. WOZ-waarde woningen
    "Woningvoorraad_35":                 "M000297",    # Woningvoorraad
    "Koopwoningen_47":                   "1014800",    # Koopwoningen %
    "HuurwoningenTotaal_48":             "1014850_2",  # Huurwoningen totaal %

    # ── Energie — 85984NED (2024) ─────────────────────────────────────────
    "GemiddeldeElektriciteitslevering_53": "M000221_2",  # Gem. elektriciteitslevering
    "GemiddeldAardgasverbruik_55":         "M000219_2",  # Gem. aardgasverbruik
    # WoningenMetZonnestroom_59 → NOT in DuckDB (suppressed by CBS at regional level)

    # ── Onderwijs — 85984NED (2024) ───────────────────────────────────────
    "LeerlingenPo_62":   "A025301",  # Leerlingen po
    # HboWo_69 → null in CBS OData at regional level (educational attainment % not published)
    "StudentenHbo_65":   "A025294",  # Studenten hbo
    "StudentenWo_66":    "A025297",  # Studenten wo

    # Arbeid (WerkzameBeroepsbevolking_70, Nettoarbeidsparticipatie_71, PercentageZelfstandigen_75)
    # → NOT mapped: CBS does NOT publish these at regional (gemeente/wijk/buurt) level.
    #   All values are null in both bulk CSV and OData TypedDataSet.

    # ── Inkomen — 85984NED (2024) ─────────────────────────────────────────
    "GemiddeldInkomenPerInwoner_78":          "M000224",  # Gem. inkomen per inwoner
    "GemiddeldInkomenPerInkomensontvanger_77":"M000223",  # Gem. inkomen per ontvanger
    "GemGestandaardiseerdInkomen_83":         "M000222",  # Gem. gestandaardiseerd inkomen
    "MediaanVermogenVanParticuliereHuish_86": "M000939",  # Mediaan vermogen
    "PersonenInArmoede_81":                   "M008349",  # Personen in armoede %

    # ── Sociale zekerheid — 85984NED (2024) ───────────────────────────────
    "PersonenPerSoortUitkeringBijstand_87": "D006842",  # Bijstand
    "PersonenPerSoortUitkeringAO_88":       "D006837",  # AO-uitkering
    "PersonenPerSoortUitkeringWW_89":       "D001827",  # WW-uitkering
    "PersonenPerSoortUitkeringAOW_90":      "D000193",  # AOW-uitkering

    # ── Zorg — 85984NED (2024) ────────────────────────────────────────────
    "JongerenMetJeugdzorgInNatura_91":  "T001203",   # Jongeren met jeugdzorg
    "WmoClienten_93":                   "M001342_1", # Wmo-cliënten

    # ── Bedrijfsvestigingen — 85984NED (2024) ─────────────────────────────
    "BedrijfsvestigingenTotaal_95":    "M000200_2",  # Bedrijfsvestigingen totaal

    # ── Motorvoertuigen — 86165NED (2025) and 85984NED (2024) ────────────
    "PersonenautoSPerHuishouden_107":  "M000368",    # Personenauto's per huishouden (suppressed for small areas)
    "PersonenautoSTotaal_104":         "A018943_2",  # Personenauto's totaal (full coverage)

    # Nabijheid (AfstandTot*) → NOT mapped in DuckDB:
    # CBS bulk CSV only has 28–44 GM-level rows (partial), while OData has complete 342 rows.
    # Removing DuckDB mappings forces the correct OData fallback for all proximity measures.

    # ── Oppervlakte — 86165NED (2025) and 85984NED (2024) ────────────────
    "OppervlakteTotaal_115":           "T001455_2", # Oppervlakte totaal
    "Omgevingsadressendichtheid_121":  "ST0003",    # Omgevingsadressendichtheid
}

# Reverse mapping (CSV Identifier → OData code) — built once at import time
_CSV_TO_ODATA: dict[str, str] = {v: k for k, v in _ODATA_TO_CSV.items()}


def _get_conn() -> duckdb.DuckDBPyConnection | None:
    global _conn
    if _conn is not None:
        return _conn
    if not _DB_PATH.exists():
        return None
    try:
        _conn = duckdb.connect(str(_DB_PATH), read_only=True)
        logger.info("DuckDB connected: %s", _DB_PATH)
    except Exception as exc:
        logger.warning("Could not open DuckDB: %s", exc)
        _conn = None
    return _conn


def _get_spatial_conn() -> duckdb.DuckDBPyConnection | None:
    """Return a read-only connection to cbs_spatial.duckdb (if it exists)."""
    global _spatial_conn
    if _spatial_conn is not None:
        # Check that the file still exists (could have been rebuilt)
        if not _SPATIAL_DB_PATH.exists():
            _spatial_conn = None
            return None
        return _spatial_conn
    if not _SPATIAL_DB_PATH.exists():
        return None
    try:
        _spatial_conn = duckdb.connect(str(_SPATIAL_DB_PATH), read_only=True)
        logger.info("Spatial DuckDB connected: %s", _SPATIAL_DB_PATH)
    except Exception as exc:
        logger.warning("Could not open spatial DuckDB: %s", exc)
        _spatial_conn = None
    return _spatial_conn


def invalidate_spatial_conn() -> None:
    """Force reconnect on next spatial query (call after a rebuild)."""
    global _spatial_conn
    if _spatial_conn is not None:
        try:
            _spatial_conn.close()
        except Exception:
            pass
        _spatial_conn = None


def _get_geo_conn() -> duckdb.DuckDBPyConnection | None:
    """Read-only connection to gemeente_geo.duckdb with the spatial extension loaded.

    Separate file from cbs_spatial.duckdb so writes during ingest never conflict
    with the read-only stats/regions singleton.
    """
    global _geo_conn
    if _geo_conn is not None:
        if not _GEO_DB_PATH.exists():
            _geo_conn = None
            return None
        return _geo_conn
    if not _GEO_DB_PATH.exists():
        return None
    try:
        conn = duckdb.connect(str(_GEO_DB_PATH), read_only=True)
        conn.execute("LOAD spatial")
        _geo_conn = conn
        logger.info("Geometry DuckDB connected (spatial ext loaded): %s", _GEO_DB_PATH)
    except Exception as exc:
        logger.warning("Could not open geometry DuckDB: %s", exc)
        _geo_conn = None
    return _geo_conn


def invalidate_geo_conn() -> None:
    """Force reconnect on next geometry query (call after ingest rebuild)."""
    global _geo_conn
    if _geo_conn is not None:
        try:
            _geo_conn.close()
        except Exception:
            pass
        _geo_conn = None


def is_available() -> bool:
    return _get_conn() is not None


def is_spatial_available() -> bool:
    return _get_spatial_conn() is not None


def _table_name(table_id: str) -> str:
    return "cbs_" + table_id.upper().replace("-", "_")


def _table_exists(conn: duckdb.DuckDBPyConnection, tbl: str) -> bool:
    try:
        result = conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [tbl]
        ).fetchone()
        return result is not None and result[0] > 0
    except Exception:
        return False


def _resolve_measure(
    conn: duckdb.DuckDBPyConnection,
    tbl: str,
    odata_code: str,
) -> str | None:
    """Translate an OData measure code to a CSV Identifier.

    Strategy:
    1. Static lookup in _ODATA_TO_CSV
    2. Title-based fuzzy match against the DuckDB measures table
    3. Return None if no match found (triggers OData fallback)
    """
    # Static lookup first
    if odata_code in _ODATA_TO_CSV:
        csv_id = _ODATA_TO_CSV[odata_code]
        # Verify this identifier actually exists in the table
        try:
            result = conn.execute(
                f"SELECT COUNT(*) FROM {tbl} WHERE Measure = ?", [csv_id]
            ).fetchone()
            if result and result[0] > 0:
                return csv_id
        except Exception:
            pass

    # Title-based match using MeasureCodes table
    measures_tbl = f"{tbl}_measures"
    if not _table_exists(conn, measures_tbl):
        return None

    # Normalise the OData code to a search term:
    # e.g. 'GemiddeldWOZWaardeVanWoningen_39' → 'gemiddeld woz waarde woningen'
    search_term = re.sub(r"_\d+$", "", odata_code)  # strip trailing _N
    search_term = re.sub(r"([A-Z])", r" \1", search_term).lower().strip()

    try:
        # Check all identifiers in the measures table for a title match
        rows = conn.execute(
            f"SELECT Identifier, Title FROM {measures_tbl} WHERE DataType IN ('Long','Double','Float','Integer')"
        ).fetchall()
    except Exception:
        return None

    for identifier, title in rows:
        if not title:
            continue
        title_lower = title.lower()
        # Simple overlap check
        words = [w for w in search_term.split() if len(w) > 3]
        if any(w in title_lower for w in words):
            # Verify this identifier has data in the observations table
            try:
                cnt = conn.execute(
                    f"SELECT COUNT(*) FROM {tbl} WHERE Measure = ?", [identifier]
                ).fetchone()
                if cnt and cnt[0] > 0:
                    logger.debug("Title match: %s → %s ('%s')", odata_code, identifier, title)
                    return identifier
            except Exception:
                pass

    return None


def _geo_where(geography_level: str, region_scope: str | None) -> str:
    prefix = {"gemeente": "GM", "wijk": "WK", "buurt": "BU"}.get(geography_level, "GM")

    if region_scope and geography_level in ("wijk", "buurt"):
        gm_digits = re.sub(r"[^0-9]", "", region_scope)
        sub = "WK" if geography_level == "wijk" else "BU"
        return f"WijkenEnBuurten LIKE '{sub}{gm_digits}%'"
    elif region_scope and geography_level == "gemeente" and region_scope.upper().startswith("GM"):
        # Exact municipality scope: match that specific GM code
        return f"WijkenEnBuurten LIKE '{region_scope}%'"
    else:
        return f"WijkenEnBuurten LIKE '{prefix}%'"


def get_observations_local(
    table_id: str,
    measure_code: str,
    geography_level: str,
    region_scope: str | None,
) -> pd.DataFrame | None:
    """Query DuckDB for CBS observations.

    Returns DataFrame with columns [RegioS, <measure_code>] on success.
    Returns None if unavailable (triggers OData fallback in cbs_client).
    """
    conn = _get_conn()
    if conn is None:
        return None

    tbl = _table_name(table_id)
    if not _table_exists(conn, tbl):
        logger.debug("DuckDB: table %s not found", tbl)
        return None

    csv_id = _resolve_measure(conn, tbl, measure_code)
    if csv_id is None:
        logger.debug("DuckDB: no mapping for %s in %s -- falling back to OData", measure_code, tbl)
        return None

    where = _geo_where(geography_level, region_scope)
    sql = f"SELECT WijkenEnBuurten, Value FROM {tbl} WHERE Measure = ? AND {where}"

    try:
        df = conn.execute(sql, [csv_id]).df()
    except Exception as exc:
        logger.warning("DuckDB query failed: %s", exc)
        return None

    if df.empty:
        logger.debug("DuckDB: no rows for %s/%s/%s", table_id, measure_code, geography_level)
        return None

    df = df.rename(columns={"WijkenEnBuurten": "RegioS", "Value": measure_code})
    df["RegioS"] = df["RegioS"].str.strip()
    df[measure_code] = pd.to_numeric(df[measure_code], errors="coerce")
    df = df.dropna(subset=[measure_code])

    # Coverage check: if fewer than 30% of expected regions have data, fall back to OData.
    # This catches measures where the bulk CSV has partial municipality coverage
    # (e.g. nabijheid/proximity measures only have 28-44 of 342 GM rows in the CSV).
    _MIN_COVERAGE = {"gemeente": 100, "wijk": 500, "buurt": 1000}
    min_rows = _MIN_COVERAGE.get(geography_level, 50)
    if region_scope is None and len(df) < min_rows:
        logger.info(
            "DuckDB: low coverage for %s/%s (%d rows < %d min) -- falling back to OData",
            table_id, measure_code, len(df), min_rows,
        )
        return None

    logger.info(
        "DuckDB HIT: %s/%s (csv=%s) level=%s scope=%s -> %d rows",
        table_id, measure_code, csv_id, geography_level, region_scope, len(df),
    )
    return df


def get_columns_local(table_id: str) -> list[dict] | None:
    """Return measure metadata for the planner/catalog.

    Returns list of {code, title, unit} using OData codes where known,
    or CSV Identifiers for unmapped measures.
    """
    conn = _get_conn()
    if conn is None:
        return None

    tbl = _table_name(table_id)
    measures_tbl = f"{tbl}_measures"
    if not _table_exists(conn, measures_tbl):
        return None

    try:
        rows = conn.execute(
            f"SELECT Identifier, Title, Unit FROM {measures_tbl} "
            f"WHERE DataType IN ('Long','Double','Float','Integer') "
            f"AND Identifier IS NOT NULL"
        ).fetchall()
    except Exception:
        return None

    result = []
    for identifier, title, unit in rows:
        # Prefer known OData code if available
        odata_code = _CSV_TO_ODATA.get(identifier, identifier)
        result.append({
            "code": odata_code,
            "title": title or identifier,
            "unit": unit or "",
            "csv_id": identifier,  # extra field for debugging
        })
    return result


def list_local_tables() -> list[str]:
    conn = _get_conn()
    if conn is None:
        return []
    try:
        rows = conn.execute("SELECT table_id FROM _meta ORDER BY table_id").fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


# ── Spatial DuckDB queries (cbs_spatial.duckdb) ───────────────────────────────

def get_neighbors_local(statcode: str, level: str) -> list[str]:
    """Return neighbor statcodes from the pre-computed adjacency table.

    Priority:
    1. ST_Touches result in gemeente_geo.duckdb (accurate topological adjacency)
    2. Coordinate-hashing result in cbs_spatial.duckdb (legacy fallback)

    Returns an empty list when neither source is available.
    """
    # 1. Spatial ST_Touches neighbors (gemeente only — that's all we store geometry for)
    if level == "gemeente":
        geo = _get_geo_conn()
        if geo is not None:
            try:
                rows = geo.execute(
                    """
                    SELECT statcode_b FROM neighbors_gemeente WHERE statcode_a = ?
                    UNION ALL
                    SELECT statcode_a FROM neighbors_gemeente WHERE statcode_b = ?
                    """,
                    [statcode, statcode],
                ).fetchall()
                if rows:
                    return [r[0] for r in rows]
            except Exception as exc:
                logger.debug("ST_Touches neighbors lookup failed: %s", exc)

    # 2. Fall back to coordinate-hashing result in cbs_spatial.duckdb
    conn = _get_spatial_conn()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT statcode_b AS neighbor FROM neighbors
            WHERE statcode_a = ? AND level = ?
            UNION ALL
            SELECT statcode_a AS neighbor FROM neighbors
            WHERE statcode_b = ? AND level = ?
            """,
            [statcode, level, statcode, level],
        ).fetchall()
        return [r[0] for r in rows]
    except Exception as exc:
        logger.debug("get_neighbors_local failed: %s", exc)
        return []


def get_region_info(statcode: str) -> dict[str, Any] | None:
    """Look up region metadata (gm_naam, province, centroid) for a statcode.

    Returns None when cbs_spatial.duckdb is not available.
    """
    conn = _get_spatial_conn()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT statnaam, level, gm_code, gm_naam, province, centroid_lon, centroid_lat "
            "FROM regions WHERE statcode = ?",
            [statcode],
        ).fetchone()
        if row is None:
            return None
        return {
            "statnaam":     row[0],
            "level":        row[1],
            "gm_code":      row[2],
            "gm_naam":      row[3],
            "province":     row[4],
            "centroid_lon": row[5],
            "centroid_lat": row[6],
        }
    except Exception as exc:
        logger.debug("get_region_info failed for %s: %s", statcode, exc)
        return None


def get_observations_spatial(
    measure_code: str,
    geography_level: str,
    region_scope: str | None,
) -> pd.DataFrame | None:
    """Query wide-format CBS data from cbs_spatial.duckdb.

    Returns DataFrame with columns [statcode, <measure_code>] or None.
    This is an alternative fast-path alongside the legacy long-format cijfers.duckdb.
    """
    conn = _get_spatial_conn()
    if conn is None:
        return None

    tbl = f"stats_{geography_level}"
    # Verify table and column exist
    try:
        cols = conn.execute(f"SELECT * FROM {tbl} LIMIT 0").description
        col_names = [c[0] for c in cols]
    except Exception:
        return None

    if measure_code not in col_names:
        return None

    # Build WHERE clause for scope
    where_parts: list[str] = []
    params: list[Any] = []
    if region_scope:
        scope = region_scope.strip().upper()
        if geography_level == "gemeente" and scope.startswith("GM"):
            where_parts.append("statcode = ?")
            params.append(scope)
        elif geography_level in ("wijk", "buurt") and scope.startswith("GM"):
            gm_digits = re.sub(r"[^0-9]", "", scope)
            prefix = "WK" if geography_level == "wijk" else "BU"
            where_parts.append(f"statcode LIKE '{prefix}{gm_digits}%'")
    else:
        prefix = {"gemeente": "GM", "wijk": "WK", "buurt": "BU"}.get(geography_level, "GM")
        where_parts.append(f"statcode LIKE '{prefix}%'")

    where = " AND ".join(where_parts) if where_parts else "1=1"
    sql = f'SELECT statcode, "{measure_code}" AS val FROM {tbl} WHERE {where}'

    try:
        df = conn.execute(sql, params).df()
    except Exception as exc:
        logger.debug("get_observations_spatial failed: %s", exc)
        return None

    if df.empty:
        return None

    df = df.rename(columns={"val": measure_code})
    df["statcode"] = df["statcode"].str.strip()
    df[measure_code] = pd.to_numeric(df[measure_code], errors="coerce")
    df = df.dropna(subset=[measure_code])
    if df.empty:
        return None  # all values were NULL → fall through to OData
    df = df.rename(columns={"statcode": "RegioS"})

    # Coverage check (same as long-format path)
    _MIN_COVERAGE = {"gemeente": 100, "wijk": 500, "buurt": 1000}
    min_rows = _MIN_COVERAGE.get(geography_level, 50)
    if region_scope is None and len(df) < min_rows:
        logger.debug(
            "Spatial DuckDB low coverage %s/%s (%d < %d) — will fall back",
            geography_level, measure_code, len(df), min_rows,
        )
        return None

    logger.info(
        "Spatial DuckDB HIT: %s/%s scope=%s → %d rows",
        geography_level, measure_code, region_scope, len(df),
    )
    return df


def get_geometries_local(geo_level: str) -> list[dict] | None:
    """Return all gemeente features from the local DuckDB geometry table.

    Returns a list of raw GeoJSON feature dicts (same format as the disk cache
    used by ``spatial_service``) so all existing Python filters apply unchanged.
    Returns ``None`` when the table is unavailable or empty.

    Only ``geo_level='gemeente'`` is supported; wijk/buurt return ``None`` and
    fall through to the PDOK / disk-cache path.
    """
    if geo_level != "gemeente":
        return None

    conn = _get_geo_conn()
    if conn is None:
        return None

    # Fast existence check
    try:
        conn.execute("SELECT 1 FROM gemeente_geo LIMIT 1")
    except Exception:
        return None  # Table doesn't exist yet

    sql = """
        SELECT statcode, statnaam, jaarcode, ST_AsGeoJSON(geom) AS geom_json
        FROM gemeente_geo
    """
    try:
        rows = conn.execute(sql).fetchall()
    except Exception as exc:
        logger.debug("get_geometries_local query failed: %s", exc)
        return None

    if not rows:
        return None

    features: list[dict] = []
    for statcode, statnaam, jaarcode, geom_json in rows:
        if not geom_json:
            continue
        try:
            geom = json.loads(geom_json)
        except Exception:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "statcode": statcode,
                "statnaam": statnaam,
                "gm_code":  "",        # gemeente level has no parent gm_code
                "jaarcode": jaarcode,
            },
            "geometry": geom,
        })

    if not features:
        return None

    logger.info("Geometry DuckDB HIT: %d gemeente features", len(features))
    return features


def get_ingest_status() -> dict[str, Any] | None:
    """Return the last row from ingest_log, or None if not available."""
    conn = _get_spatial_conn()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT run_id, started_at, finished_at, status, region_count, "
            "neighbor_count, notes "
            "FROM ingest_log ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {
            "run_id":         row[0],
            "started_at":     str(row[1]) if row[1] else None,
            "finished_at":    str(row[2]) if row[2] else None,
            "status":         row[3],
            "region_count":   row[4],
            "neighbor_count": row[5],
            "notes":          row[6],
        }
    except Exception as exc:
        logger.debug("get_ingest_status failed: %s", exc)
        return None
