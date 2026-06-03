"""CBS + PDOK spatial preprocessing pipeline.

Builds ``backend/data/cbs_spatial.duckdb`` with:

  regions        — one row per statcode: centroid, gm_naam, province, level
  neighbors      — shared-boundary adjacency (coord hashing, ≥2 shared vertices)
  stats_gemeente — wide-format CBS measures for all gemeenten
  stats_wijk     — wide-format CBS measures for all wijken
  stats_buurt    — wide-format CBS measures for all buurten
  ingest_log     — timestamped run history

Designed to run as a background task (``asyncio``).
Call ``run_ingest()`` — it is safe to call from an endpoint.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import httpx
import pandas as pd

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Paths ─────────────────────────────────────────────────────────────────────

_DATA_DIR   = Path(__file__).parent / "data"
_GEOM_DIR   = _DATA_DIR / "geometry"
_DB_PATH    = _DATA_DIR / "cbs_spatial.duckdb"
_GEO_DB_PATH = _DATA_DIR / "gemeente_geo.duckdb"   # separate file — avoids DuckDB read/write lock conflict

_PROVINCE_MAP_PATH = _GEOM_DIR / "province_gm_map.json"

# CBS tables to ingest (newest first; merged per level later)
_CBS_TABLES = ["86165NED", "85984NED"]

_LEVEL_PREFIX = {"gemeente": "GM", "wijk": "WK", "buurt": "BU"}

_PAGE_SIZE = 10_000

# ── Shared run-state (updated in-place by run_ingest) ─────────────────────────

_status: dict[str, Any] = {
    "status":     "idle",        # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "progress":   "",
    "region_counts": {},
    "neighbor_count": 0,
    "notes": [],
}


def get_status() -> dict[str, Any]:
    """Return a JSON-serialisable snapshot of the last (or current) run."""
    return dict(_status)


# ── Geometry helpers (no spatial_service import to avoid circular deps) ────────

def _load_raw_features(level: str) -> list[dict]:
    path = _GEOM_DIR / f"{level}_raw.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read disk cache for %s: %s", level, exc)
        return []


def _flatten_coords(geom: dict) -> list[tuple[float, float]]:
    """Collect all (lon, lat) pairs from any GeoJSON geometry type."""
    coords: list[tuple[float, float]] = []

    def _walk(g: dict) -> None:
        t = g["type"]
        if t == "Point":
            coords.append(tuple(g["coordinates"][:2]))  # type: ignore[arg-type]
        elif t in ("LineString", "MultiPoint"):
            coords.extend(tuple(c[:2]) for c in g["coordinates"])  # type: ignore[misc]
        elif t in ("Polygon", "MultiLineString"):
            for ring in g["coordinates"]:
                coords.extend(tuple(c[:2]) for c in ring)  # type: ignore[misc]
        elif t == "MultiPolygon":
            for poly in g["coordinates"]:
                for ring in poly:
                    coords.extend(tuple(c[:2]) for c in ring)  # type: ignore[misc]
        elif t == "GeometryCollection":
            for sub in g.get("geometries", []):
                _walk(sub)

    _walk(geom)
    return coords


def _centroid(feature: dict) -> tuple[float, float]:
    geom = feature.get("geometry")
    if not geom:
        return (0.0, 0.0)
    pts = _flatten_coords(geom)
    if not pts:
        return (0.0, 0.0)
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _filter_by_year(features: list[dict], year: int) -> list[dict]:
    matched = [f for f in features if f.get("properties", {}).get("jaarcode") == year]
    if matched:
        return matched
    jaarcodes = [
        f["properties"]["jaarcode"]
        for f in features
        if f.get("properties", {}).get("jaarcode") is not None
    ]
    if not jaarcodes:
        return features
    latest = max(jaarcodes)
    return [f for f in features if f.get("properties", {}).get("jaarcode") == latest]


# ── Neighbor computation ───────────────────────────────────────────────────────

def _compute_neighbors(features: list[dict], level: str) -> list[tuple[str, str, int]]:
    """Shared-boundary adjacency via coordinate hashing.

    Strategy
    --------
    Round every vertex to 4 decimal places (≈ 11 m at 52 °N).  Two features
    that share a boundary will have identical rounded vertices at that boundary.
    We build an inverted index ``coord → [statcodes]`` and count how many
    shared vertices each pair of regions has.  Pairs with ≥ 2 shared vertices
    are considered *neighbors*.

    Returns
    -------
    list of (statcode_a, statcode_b, shared_vertex_count)  — sorted (a < b).
    """
    logger.info("Computing neighbors for %s (%d features) …", level, len(features))

    # coord_hash → list[statcode]
    coord_index: dict[tuple[float, float], list[str]] = defaultdict(list)

    for f in features:
        props = f.get("properties", {})
        statcode = str(props.get("statcode", "")).strip()
        if not statcode:
            continue
        geom = f.get("geometry")
        if not geom:
            continue

        seen: set[tuple[float, float]] = set()
        for lon, lat in _flatten_coords(geom):
            rounded = (round(lon, 4), round(lat, 4))
            if rounded not in seen:
                coord_index[rounded].append(statcode)
                seen.add(rounded)

    # Count shared vertices between each ordered pair
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for codes in coord_index.values():
        if len(codes) < 2:
            continue
        # De-duplicate codes at this coordinate
        unique = list(dict.fromkeys(codes))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                key = (unique[i], unique[j]) if unique[i] < unique[j] else (unique[j], unique[i])
                pair_counts[key] += 1

    results = [
        (a, b, cnt)
        for (a, b), cnt in pair_counts.items()
        if cnt >= 2
    ]
    logger.info(
        "Neighbors for %s: %d pairs with ≥2 shared vertices (from %d total pairs)",
        level, len(results), len(pair_counts),
    )
    return results


# ── CBS OData fetching ─────────────────────────────────────────────────────────

async def _fetch_data_properties(table_id: str) -> list[dict]:
    url = f"{settings.CBS_ODATA_BASE}/{table_id}/DataProperties"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, params={"$format": "json"})
        resp.raise_for_status()
        return resp.json().get("value", [])


async def _fetch_cbs_wide(
    table_id: str,
    geography_level: str,
) -> pd.DataFrame | None:
    """Fetch ALL numeric columns from a CBS kerncijfers table for one geo level.

    Returns a wide-format DataFrame with ``statcode`` as the first column and
    one column per CBS Topic measure.  Returns ``None`` on failure.
    """
    prefix = _LEVEL_PREFIX[geography_level]
    logger.info("CBS OData: fetching %s / %s …", table_id, geography_level)

    try:
        props = await _fetch_data_properties(table_id)
    except Exception as exc:
        logger.warning("Could not fetch DataProperties for %s: %s", table_id, exc)
        return None

    # Identify geo column and all numeric Topic columns
    geo_col = "WijkenEnBuurten"
    numeric_cols: list[str] = []
    for p in props:
        ptype = str(p.get("Type", "")).lower()
        key = str(p.get("Key", "")).strip()
        if not key:
            continue
        if ptype in ("geodetail", "geodimension", "geodetailsize"):
            geo_col = key
        elif ptype in ("topic", "topicgroup") and key:
            numeric_cols.append(key)

    if not numeric_cols:
        logger.warning("No numeric columns for %s", table_id)
        return None

    # CBS OData $select has a URL-length limit; batch into chunks of 50 columns
    _CHUNK = 50
    all_dfs: list[pd.DataFrame] = []
    url = f"{settings.CBS_ODATA_BASE}/{table_id}/TypedDataSet"
    region_filter = f"startswith({geo_col},'{prefix}')"

    for chunk_start in range(0, len(numeric_cols), _CHUNK):
        chunk = numeric_cols[chunk_start : chunk_start + _CHUNK]
        select = ",".join([geo_col] + chunk)

        rows: list[dict] = []
        skip = 0
        async with httpx.AsyncClient(timeout=120.0) as client:
            while True:
                params = {
                    "$select": select,
                    "$filter": region_filter,
                    "$top": _PAGE_SIZE,
                    "$skip": skip,
                    "$format": "json",
                }
                try:
                    resp = await client.get(url, params=params, timeout=120.0)
                    resp.raise_for_status()
                except Exception as exc:
                    logger.warning(
                        "CBS request failed for %s/%s chunk %d: %s",
                        table_id, geography_level, chunk_start // _CHUNK, exc,
                    )
                    break

                batch = resp.json().get("value", [])
                rows.extend(batch)
                if len(batch) < _PAGE_SIZE:
                    break
                skip += _PAGE_SIZE
                await asyncio.sleep(0.1)  # be polite to CBS

        if rows:
            chunk_df = pd.DataFrame(rows)
            # Normalise geo column name → "statcode"
            if geo_col in chunk_df.columns and geo_col != "statcode":
                chunk_df = chunk_df.rename(columns={geo_col: "statcode"})
            chunk_df["statcode"] = chunk_df["statcode"].str.strip()

            # Coerce numeric columns
            for col in chunk:
                if col in chunk_df.columns:
                    chunk_df[col] = pd.to_numeric(chunk_df[col], errors="coerce")

            all_dfs.append(chunk_df)
            logger.info(
                "  %s/%s chunk %d/%d → %d rows × %d cols",
                table_id, geography_level,
                chunk_start // _CHUNK + 1, (len(numeric_cols) - 1) // _CHUNK + 1,
                len(chunk_df), len(chunk_df.columns),
            )

    if not all_dfs:
        return None

    # Merge all column-chunks on statcode
    df = all_dfs[0]
    for other in all_dfs[1:]:
        df = df.merge(other, on="statcode", how="outer", suffixes=("", "_dup"))
        # Drop any duplicate columns (shouldn't happen but be safe)
        dup_cols = [c for c in df.columns if c.endswith("_dup")]
        df = df.drop(columns=dup_cols)

    logger.info(
        "CBS OData %s/%s complete: %d rows × %d cols",
        table_id, geography_level, len(df), len(df.columns),
    )
    return df


# ── Regions table ──────────────────────────────────────────────────────────────

def _build_regions_df(
    features_by_level: dict[str, list[dict]],
    province_map: dict[str, list[str]],
) -> pd.DataFrame:
    """Build a flat regions DataFrame from PDOK geometry features.

    Columns: statcode, statnaam, level, gm_code, gm_naam, province,
             centroid_lon, centroid_lat
    """
    # Reverse map: gm_code → gm_naam (from gemeente features)
    gm_naam_map: dict[str, str] = {}
    for f in features_by_level.get("gemeente", []):
        props = f.get("properties", {})
        code = str(props.get("statcode", "")).strip()
        naam = str(props.get("statnaam", "")).strip()
        if code and naam:
            gm_naam_map[code] = naam

    # Reverse map: gm_code → province name
    gm_province: dict[str, str] = {}
    for prov_name, gm_codes in province_map.items():
        for gm_code in gm_codes:
            gm_province[gm_code.upper()] = prov_name

    rows: list[dict] = []
    for level, features in features_by_level.items():
        for f in features:
            props = f.get("properties", {})
            statcode = str(props.get("statcode", "")).strip()
            if not statcode:
                continue
            cx, cy = _centroid(f)
            gm_code = (
                statcode if level == "gemeente"
                else str(props.get("gm_code", "")).strip()
            )
            rows.append({
                "statcode":     statcode,
                "statnaam":     str(props.get("statnaam", "")).strip(),
                "level":        level,
                "gm_code":      gm_code,
                "gm_naam":      gm_naam_map.get(gm_code, ""),
                "province":     gm_province.get(gm_code.upper(), ""),
                "centroid_lon": round(cx, 6),
                "centroid_lat": round(cy, 6),
            })

    return pd.DataFrame(rows)


# ── DuckDB writer ──────────────────────────────────────────────────────────────

def _write_db(
    regions_df: pd.DataFrame,
    neighbors_by_level: dict[str, list[tuple[str, str, int]]],
    stats_by_level: dict[str, pd.DataFrame | None],
    started_at: datetime,
) -> dict[str, int]:
    """Write all tables to cbs_spatial.duckdb.  Returns row-count dict."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(_DB_PATH))
    try:
        # ── regions ───────────────────────────────────────────────────────────
        conn.execute("DROP TABLE IF EXISTS regions")
        conn.execute("""
            CREATE TABLE regions (
                statcode     VARCHAR PRIMARY KEY,
                statnaam     VARCHAR,
                level        VARCHAR,
                gm_code      VARCHAR,
                gm_naam      VARCHAR,
                province     VARCHAR,
                centroid_lon DOUBLE,
                centroid_lat DOUBLE
            )
        """)
        conn.execute("INSERT INTO regions SELECT * FROM regions_df")
        n_regions = len(regions_df)

        # ── neighbors ─────────────────────────────────────────────────────────
        conn.execute("DROP TABLE IF EXISTS neighbors")
        conn.execute("""
            CREATE TABLE neighbors (
                statcode_a     VARCHAR,
                statcode_b     VARCHAR,
                level          VARCHAR,
                shared_points  INTEGER,
                PRIMARY KEY (statcode_a, statcode_b, level)
            )
        """)
        n_neighbors = 0
        for level, pairs in neighbors_by_level.items():
            if not pairs:
                continue
            nb_df = pd.DataFrame(pairs, columns=["statcode_a", "statcode_b", "shared_points"])
            nb_df["level"] = level
            conn.execute(
                "INSERT INTO neighbors SELECT statcode_a, statcode_b, level, shared_points FROM nb_df"
            )
            n_neighbors += len(nb_df)

        # ── stats tables ──────────────────────────────────────────────────────
        stats_counts: dict[str, int] = {}
        for level, df in stats_by_level.items():
            tbl = f"stats_{level}"
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
            if df is not None and not df.empty:
                conn.execute(f"CREATE TABLE {tbl} AS SELECT * FROM df")
                stats_counts[level] = len(df)
            else:
                conn.execute(f"CREATE TABLE {tbl} (statcode VARCHAR)")
                stats_counts[level] = 0

        # ── ingest_log ────────────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ingest_log (
                run_id        INTEGER,
                started_at    TIMESTAMP,
                finished_at   TIMESTAMP,
                status        VARCHAR,
                region_count  INTEGER,
                neighbor_count INTEGER,
                notes         VARCHAR
            )
        """)
        run_id_row = conn.execute("SELECT COALESCE(MAX(run_id), 0) + 1 FROM ingest_log").fetchone()
        run_id = run_id_row[0] if run_id_row else 1
        finished_at = datetime.now(timezone.utc)
        conn.execute(
            "INSERT INTO ingest_log VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                started_at.replace(tzinfo=None),
                finished_at.replace(tzinfo=None),
                "done",
                n_regions,
                n_neighbors,
                json.dumps(stats_counts),
            ],
        )

        logger.info(
            "cbs_spatial.duckdb written: %d regions, %d neighbor pairs, stats=%s",
            n_regions, n_neighbors, stats_counts,
        )
        return {"regions": n_regions, "neighbors": n_neighbors, **stats_counts}

    finally:
        conn.close()


# ── Geometry writer (DuckDB spatial) ──────────────────────────────────────────

def _write_geometry_db(
    gemeente_features: list[dict],
    regions_df: pd.DataFrame,
) -> int:
    """Store gemeente polygon geometry in cbs_spatial.duckdb.

    Creates (or replaces) the ``gemeente_geo`` table::

        statcode TEXT, statnaam TEXT, province TEXT, jaarcode INTEGER, geom GEOMETRY

    Requires the DuckDB spatial extension (installed automatically on first run).
    Returns the number of rows inserted.
    """
    # Build statcode → province lookup from the already-built regions table
    province_map: dict[str, str] = {}
    if not regions_df.empty and {"statcode", "level", "province"}.issubset(regions_df.columns):
        gm_rows = regions_df[regions_df["level"] == "gemeente"]
        for _, row in gm_rows.iterrows():
            sc = str(row["statcode"]).strip().upper()
            prov = str(row.get("province", "")).strip()
            if sc:
                province_map[sc] = prov

    # Write to a SEPARATE file so the read-only cbs_spatial.duckdb singleton is never blocked
    conn = duckdb.connect(str(_GEO_DB_PATH))
    try:
        # Install + load spatial extension (idempotent; installs to ~/.duckdb/extensions/)
        conn.execute("INSTALL spatial")
        conn.execute("LOAD spatial")

        conn.execute("DROP TABLE IF EXISTS gemeente_geo")
        conn.execute("""
            CREATE TABLE gemeente_geo (
                statcode TEXT NOT NULL,
                statnaam TEXT,
                province TEXT,
                jaarcode INTEGER,
                geom     GEOMETRY
            )
        """)

        inserted = 0
        for f in gemeente_features:
            props    = f.get("properties") or {}
            statcode = str(props.get("statcode", "")).strip().upper()
            statnaam = str(props.get("statnaam", "")).strip()
            jaarcode = props.get("jaarcode")
            geom     = f.get("geometry")
            if not statcode or geom is None:
                continue

            province  = province_map.get(statcode, "")
            geom_json = json.dumps(geom)
            try:
                conn.execute(
                    "INSERT INTO gemeente_geo VALUES (?, ?, ?, ?, ST_GeomFromGeoJSON(?))",
                    [statcode, statnaam, province, jaarcode, geom_json],
                )
                inserted += 1
            except Exception as exc:
                logger.warning("gemeente_geo: skip %s — %s", statcode, exc)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_gg_statcode ON gemeente_geo(statcode)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gg_province ON gemeente_geo(province)")

        logger.info("gemeente_geo: %d features written to cbs_spatial.duckdb", inserted)
        return inserted

    except Exception as exc:
        logger.error("_write_geometry_db failed: %s", exc)
        return 0
    finally:
        conn.close()


# ── Main entry point ───────────────────────────────────────────────────────────

async def run_ingest(year: int | None = None) -> dict[str, Any]:
    """Run the full ingestion pipeline.

    Downloads CBS data + reads cached PDOK geometry, computes shared-boundary
    adjacency, and writes ``cbs_spatial.duckdb``.

    Safe to call from an endpoint (non-blocking — use ``asyncio.create_task``).
    Updates ``get_status()`` throughout.
    """
    global _status

    if _status["status"] == "running":
        logger.warning("Ingest already running — skipping duplicate call")
        return _status

    started_at = datetime.now(timezone.utc)
    _status.update({
        "status":     "running",
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "progress":   "Starting …",
        "region_counts": {},
        "neighbor_count": 0,
        "notes": [],
    })

    try:
        geo_year = year or settings.DEFAULT_GEO_YEAR

        # ── Step 1: Load PDOK geometry from disk cache ─────────────────────────
        _status["progress"] = "Loading PDOK geometry …"
        features_by_level: dict[str, list[dict]] = {}

        for level in ("gemeente", "wijk", "buurt"):
            raw = _load_raw_features(level)
            if not raw:
                note = f"⚠ No disk cache for {level} — run the app first to warm up geometry."
                logger.warning(note)
                _status["notes"].append(note)
                # Try to fetch from PDOK directly as a fallback
                raw = await _fetch_pdok_level(level)
                if raw:
                    # Save to disk for future runs
                    try:
                        _GEOM_DIR.mkdir(parents=True, exist_ok=True)
                        (_GEOM_DIR / f"{level}_raw.json").write_text(
                            json.dumps(raw, ensure_ascii=False), encoding="utf-8"
                        )
                        logger.info("Fetched and cached %d raw %s features", len(raw), level)
                    except Exception as exc:
                        logger.warning("Could not save %s disk cache: %s", level, exc)

            year_features = _filter_by_year(raw, geo_year) if raw else []
            features_by_level[level] = year_features
            _status["region_counts"][level] = len(year_features)
            logger.info("Loaded %d %s features (year=%d)", len(year_features), level, geo_year)

        # ── Step 2: Load province map ──────────────────────────────────────────
        _status["progress"] = "Loading province map …"
        province_map: dict[str, list[str]] = {}
        if _PROVINCE_MAP_PATH.exists():
            try:
                raw_prov = json.loads(_PROVINCE_MAP_PATH.read_text(encoding="utf-8"))
                province_map = {k: list(v) for k, v in raw_prov.items()}
                logger.info("Province map loaded (%d provinces)", len(province_map))
            except Exception as exc:
                logger.warning("Could not load province map: %s", exc)
        else:
            note = "⚠ Province map not found — province column will be empty. Start the app once to build it."
            _status["notes"].append(note)
            logger.warning(note)

        # ── Step 3: Build regions table ────────────────────────────────────────
        _status["progress"] = "Building regions table …"
        regions_df = _build_regions_df(features_by_level, province_map)
        logger.info("Regions table: %d rows", len(regions_df))

        # ── Step 4: Compute neighbors ──────────────────────────────────────────
        neighbors_by_level: dict[str, list[tuple[str, str, int]]] = {}
        for level in ("gemeente", "wijk", "buurt"):
            _status["progress"] = f"Computing neighbors: {level} …"
            feats = features_by_level.get(level, [])
            if feats:
                # Use asyncio.to_thread for CPU-heavy work so the event loop stays free
                pairs = await asyncio.to_thread(_compute_neighbors, feats, level)
            else:
                pairs = []
            neighbors_by_level[level] = pairs

        total_neighbors = sum(len(p) for p in neighbors_by_level.values())
        _status["neighbor_count"] = total_neighbors
        logger.info("Total neighbor pairs: %d", total_neighbors)

        # ── Step 5: Fetch CBS wide-format stats ────────────────────────────────
        stats_by_level: dict[str, pd.DataFrame | None] = {}
        for level in ("gemeente", "wijk", "buurt"):
            _status["progress"] = f"Fetching CBS stats: {level} …"

            dfs: list[pd.DataFrame] = []
            for table_id in _CBS_TABLES:
                _status["progress"] = f"Fetching CBS {table_id} / {level} …"
                df = await _fetch_cbs_wide(table_id, level)
                if df is not None:
                    dfs.append(df)

            if not dfs:
                stats_by_level[level] = None
                continue

            # Merge: start from first (86165NED = newest), outer-join with 85984NED
            merged = dfs[0]
            for other in dfs[1:]:
                # Only add columns that aren't already in merged
                new_cols = [c for c in other.columns if c not in merged.columns or c == "statcode"]
                if len(new_cols) <= 1:
                    continue  # Nothing new
                merged = merged.merge(other[new_cols], on="statcode", how="outer")

            stats_by_level[level] = merged
            logger.info(
                "Stats %s: %d rows × %d columns",
                level, len(merged), len(merged.columns),
            )

        # Close all read-only singletons before opening write connections
        try:
            from duckdb_client import invalidate_spatial_conn, invalidate_geo_conn
            invalidate_spatial_conn()
            invalidate_geo_conn()
        except Exception as exc:
            logger.debug("Connection invalidation skipped: %s", exc)

        # ── Step 6: Write DuckDB ───────────────────────────────────────────────
        _status["progress"] = "Writing cbs_spatial.duckdb …"
        counts = await asyncio.to_thread(
            _write_db, regions_df, neighbors_by_level, stats_by_level, started_at
        )

        # ── Step 7: Write gemeente polygon geometry ────────────────────────────
        gem_features = features_by_level.get("gemeente", [])
        if gem_features:
            _status["progress"] = "Writing gemeente geometry (DuckDB spatial) …"
            n_geom = await asyncio.to_thread(_write_geometry_db, gem_features, regions_df)
            counts["gemeente_geo"] = n_geom
            logger.info("gemeente_geo: %d features", n_geom)

        _status.update({
            "status":       "done",
            "finished_at":  datetime.now(timezone.utc).isoformat(),
            "progress":     "Done",
            "region_counts": {k: v for k, v in counts.items() if k in ("gemeente", "wijk", "buurt", "regions")},
            "neighbor_count": counts.get("neighbors", 0),
        })
        logger.info("Ingest complete: %s", counts)
        return _status

    except Exception as exc:
        logger.exception("Ingest failed: %s", exc)
        _status.update({
            "status":      "error",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "progress":    f"Error: {exc}",
        })
        _status["notes"].append(f"Fatal error: {exc}")
        return _status


# ── PDOK fallback fetch (if disk cache is empty) ───────────────────────────────

_COLLECTION_MAP = {
    "gemeente": "gemeente_gegeneraliseerd",
    "wijk":     "wijk_gegeneraliseerd",
    "buurt":    "buurt_gegeneraliseerd",
}
_PAGE_LIMIT = 100
_TIMEOUT    = 60.0


async def _fetch_pdok_level(level: str) -> list[dict]:
    """Fetch all PDOK features for one level (no filter — PDOK rejects CQL)."""
    collection = _COLLECTION_MAP.get(level)
    if not collection:
        return []

    base_url = f"{settings.PDOK_OGC_BASE}/collections/{collection}/items"
    features: list[dict] = []
    next_url: str | None = base_url
    first = True

    logger.info("Fetching PDOK %s from scratch …", level)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        while next_url:
            try:
                if first:
                    resp = await client.get(
                        next_url, params={"f": "json", "limit": str(_PAGE_LIMIT)}
                    )
                    first = False
                else:
                    resp = await client.get(next_url)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("PDOK fetch error for %s: %s", level, exc)
                break

            features.extend(data.get("features", []))
            next_url = None
            for link in data.get("links", []):
                if link.get("rel") == "next":
                    next_url = link.get("href")
                    break

    logger.info("PDOK %s: fetched %d raw features", level, len(features))
    return features
