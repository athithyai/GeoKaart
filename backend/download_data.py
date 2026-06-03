"""Download CBS regional statistics CSVs + gemeente boundaries into DuckDB.

Covers all 12 CBS categories shown on the data portal:
  Bevolking, Wonen en vastgoed, Energie, Onderwijs, Arbeid, Inkomen,
  Sociale zekerheid, Zorg, Bedrijfsvestigingen, Motorvoertuigen,
  Nabijheid van voorzieningen, Oppervlakte

Usage
-----
    cd backend
    python download_data.py              # download stats + geometry
    python download_data.py --no-geo     # skip geometry download
    python download_data.py --tables 86165NED 85984NED
    python download_data.py --list       # show locally stored tables

Output
------
  data/cijfers.duckdb      — long-format CBS statistics (existing)
  data/gemeente_geo.duckdb — gemeente polygon geometry (from CBS GeoPackage)

CBS CSV format
--------------
The bulk endpoint returns a ZIP containing Observations.csv (long format):
  Id ; Measure ; WijkenEnBuurten ; Value ; StringValue ; ValueAttribute
  Where Measure = the CSV Identifier (e.g. 'T001036' for 'Aantal inwoners')
  and WijkenEnBuurten = region code (e.g. 'GM0344', 'WK034400', 'BU03440000')

MeasureCodes.csv inside the same ZIP provides Identifier→Title mapping.

CBS GeoPackage
--------------
CBS publishes annual gemeente boundary files:
  https://download.cbs.nl/regionale-kaarten/gem_{year}_v1.zip
  → gem_{year}_v1.gpkg  (WGS84, statcode=GM####, statnaam, geometry)
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
import zipfile
from pathlib import Path

import duckdb
import httpx
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ── CBS bulk CSV endpoint ──────────────────────────────────────────────────────
_CSV_BASE = "https://datasets.cbs.nl/csv/CBS/nl"

# ── Output paths ──────────────────────────────────────────────────────────────
_DATA_DIR    = Path(__file__).parent / "data"
_DB_PATH     = _DATA_DIR / "cijfers.duckdb"
_GEO_DB_PATH = _DATA_DIR / "gemeente_geo.duckdb"

# CBS gebiedsindelingen GeoPackage — multi-year (2016–present), all gemeente boundaries
_GEO_URL = "https://geodata.cbs.nl/files/Gebiedsindelingen/cbsgebiedsindelingen2016_heden.zip"
_GEO_YEAR = 2024

# ── Tables to download ─────────────────────────────────────────────────────────
# Kerncijfers tables cover ALL 12 CBS categories in one table.
TABLES: dict[str, str] = {
    "86165NED": "Kerncijfers wijken en buurten 2025",  # primary — all 12 categories
    "85984NED": "Kerncijfers wijken en buurten 2024",  # year-over-year comparison
    "85618NED": "Kerncijfers wijken en buurten 2023",  # 3-year history
    "86258NED": "Arbeidsdeelname wijken en buurten 2024",   # deeper labor data
    "86232NED": "Opleidingsniveau wijken en buurten 2024",  # deeper education data
}


def _duckdb_table_name(table_id: str) -> str:
    return "cbs_" + table_id.upper().replace("-", "_")


def download_table(table_id: str, description: str, db: duckdb.DuckDBPyConnection) -> bool:
    """Download one CBS table ZIP and load into DuckDB. Returns True on success."""
    url = f"{_CSV_BASE}/{table_id}"
    tbl = _duckdb_table_name(table_id)
    logger.info("Downloading %s  (%s)", table_id, description)
    logger.info("   URL: %s", url)

    try:
        with httpx.Client(timeout=180.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("   HTTP %s -- skipping %s", exc.response.status_code, table_id)
        return False
    except Exception as exc:
        logger.warning("   Download failed for %s: %s", table_id, exc)
        return False

    content = resp.content
    logger.info("   ZIP size: %.1f MB", len(content) / 1_048_576)

    # CBS delivers a ZIP containing Observations.csv + metadata CSVs
    if content[:2] != b"PK":
        logger.warning("   Not a ZIP file for %s (unexpected format)", table_id)
        return False

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()

            # ── Load Observations.csv (long format) ──────────────────────────
            obs_name = next(
                (n for n in names if "Observations" in n and n.endswith(".csv")), None
            )
            if not obs_name:
                logger.warning("   No Observations.csv in ZIP for %s", table_id)
                return False

            obs_bytes = zf.read(obs_name)
            logger.info("   Observations.csv: %.1f MB uncompressed", len(obs_bytes) / 1_048_576)

            obs = pd.read_csv(
                io.BytesIO(obs_bytes),
                sep=";",
                dtype={"Id": "Int64", "Measure": str, "WijkenEnBuurten": str,
                       "Value": str, "StringValue": str, "ValueAttribute": str},
                na_values=["", " "],
                keep_default_na=False,
            )
            obs.columns = obs.columns.str.strip()

            # Keep only relevant columns
            obs = obs[["Measure", "WijkenEnBuurten", "Value"]].copy()
            obs["WijkenEnBuurten"] = obs["WijkenEnBuurten"].str.strip()
            obs["Measure"] = obs["Measure"].str.strip()

            # Coerce Value to float (CBS stores numeric values here)
            obs["Value"] = pd.to_numeric(obs["Value"], errors="coerce")

            # Drop rows where Value is null (string measures have no Value)
            obs = obs.dropna(subset=["Value"])

            logger.info("   Rows after filtering: %d", len(obs))

            # Write observations table
            db.execute(f"DROP TABLE IF EXISTS {tbl}")
            db.register("_obs", obs)
            db.execute(f"CREATE TABLE {tbl} AS SELECT * FROM _obs")
            db.unregister("_obs")

            # ── Load MeasureCodes.csv (identifier → title mapping) ───────────
            mc_name = next((n for n in names if "MeasureCodes" in n), None)
            if mc_name:
                mc_bytes = zf.read(mc_name)
                mc = pd.read_csv(
                    io.BytesIO(mc_bytes), sep=";", dtype=str, na_values=[""]
                )
                mc.columns = mc.columns.str.strip()
                mc_tbl = f"{tbl}_measures"
                db.execute(f"DROP TABLE IF EXISTS {mc_tbl}")
                db.register("_mc", mc)
                db.execute(f"CREATE TABLE {mc_tbl} AS SELECT * FROM _mc")
                db.unregister("_mc")
                logger.info("   Measure codes: %d entries in %s", len(mc), mc_tbl)

    except Exception as exc:
        logger.warning("   Processing failed for %s: %s", table_id, exc)
        return False

    logger.info("   Saved to DuckDB table: %s", tbl)
    return True


def record_meta(db: duckdb.DuckDBPyConnection, table_id: str, description: str) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS _meta (
            table_id    VARCHAR PRIMARY KEY,
            description VARCHAR,
            downloaded_at TIMESTAMP DEFAULT current_timestamp
        )
    """)
    db.execute(
        "INSERT OR REPLACE INTO _meta VALUES (?, ?, current_timestamp)",
        [table_id, description],
    )


def list_local(db: duckdb.DuckDBPyConnection) -> None:
    try:
        rows = db.execute(
            "SELECT table_id, description, downloaded_at FROM _meta ORDER BY table_id"
        ).fetchall()
        if not rows:
            print("No tables downloaded yet.")
            return
        print(f"\n{'Table ID':<14} {'Downloaded':<22} Description")
        print("-" * 70)
        for tid, desc, ts in rows:
            print(f"{tid:<14} {str(ts)[:19]:<22} {desc}")
    except Exception:
        print("No metadata found -- run download_data.py first.")


def download_geometry(year: int = _GEO_YEAR) -> bool:
    """Load gemeente polygon geometry into gemeente_geo.duckdb.

    Reads the PDOK GeoJSON disk cache (data/geometry/gemeente_raw.json) that the
    app already writes on first startup — no extra download needed.  Uses DuckDB
    spatial ``ST_GeomFromGeoJSON()`` to store polygons as native GEOMETRY.

    The result is a ``gemeente_geo`` table::

        statcode TEXT, statnaam TEXT, jaarcode INTEGER, geom GEOMETRY

    Returns True on success.
    """
    import json as _json

    geom_dir = _DATA_DIR / "geometry"
    cache_path = geom_dir / "gemeente_raw.json"

    if not cache_path.exists():
        logger.warning(
            "   %s not found. Start the backend once so it fetches gemeente geometry from PDOK, "
            "then re-run this script.", cache_path
        )
        return False

    logger.info("Loading gemeente geometry from disk cache: %s", cache_path)
    features = _json.loads(cache_path.read_text(encoding="utf-8"))
    logger.info("   %d raw features loaded", len(features))

    # Filter to requested year
    year_features = [
        f for f in features
        if f.get("properties", {}).get("jaarcode") == year
    ]
    if not year_features:
        # Fall back to latest available year
        jaarcodes = [f["properties"]["jaarcode"] for f in features if f.get("properties", {}).get("jaarcode")]
        if jaarcodes:
            latest = max(jaarcodes)
            year_features = [f for f in features if f.get("properties", {}).get("jaarcode") == latest]
            logger.info("   Year %d not found — using %d (%d features)", year, latest, len(year_features))
        else:
            year_features = features
            logger.info("   No jaarcode found — using all %d features", len(year_features))

    try:
        db = duckdb.connect(str(_GEO_DB_PATH))
        db.execute("INSTALL spatial")
        db.execute("LOAD spatial")

        db.execute("DROP TABLE IF EXISTS gemeente_geo")
        db.execute("""
            CREATE TABLE gemeente_geo (
                statcode TEXT NOT NULL,
                statnaam TEXT,
                jaarcode INTEGER,
                geom     GEOMETRY
            )
        """)

        inserted = 0
        for f in year_features:
            props    = f.get("properties") or {}
            statcode = str(props.get("statcode", "")).strip().upper()
            statnaam = str(props.get("statnaam", "")).strip()
            jaarcode = props.get("jaarcode")
            geom     = f.get("geometry")
            if not statcode or geom is None:
                continue
            try:
                db.execute(
                    "INSERT INTO gemeente_geo VALUES (?, ?, ?, ST_GeomFromGeoJSON(?))",
                    [statcode, statnaam, jaarcode, _json.dumps(geom)],
                )
                inserted += 1
            except Exception as exc:
                logger.debug("   Skip %s: %s", statcode, exc)

        db.execute("CREATE INDEX IF NOT EXISTS idx_gg_statcode ON gemeente_geo(statcode)")
        db.close()

        logger.info("   gemeente_geo: %d features written to %s", inserted, _GEO_DB_PATH)
        return inserted > 0

    except Exception as exc:
        logger.warning("   DuckDB spatial write failed: %s", exc)
        return False


def compute_neighbors_spatial() -> bool:
    """Compute gemeente adjacency via ST_Touches and store in gemeente_geo.duckdb.

    Replaces the coordinate-hashing approximation in ingest.py with a proper
    topological predicate.  Two municipalities are neighbors when their polygon
    boundaries touch (share at least one point / segment).

    Writes ``neighbors_gemeente (statcode_a TEXT, statcode_b TEXT)`` to
    gemeente_geo.duckdb.  Returns True on success.
    """
    if not _GEO_DB_PATH.exists():
        logger.warning("gemeente_geo.duckdb not found — run download_geometry() first")
        return False

    logger.info("Computing gemeente neighbors with ST_Touches …")

    try:
        db = duckdb.connect(str(_GEO_DB_PATH))
        db.execute("LOAD spatial")

        db.execute("DROP TABLE IF EXISTS neighbors_gemeente")
        db.execute("""
            CREATE TABLE neighbors_gemeente AS
            SELECT a.statcode AS statcode_a,
                   b.statcode AS statcode_b
            FROM   gemeente_geo a,
                   gemeente_geo b
            WHERE  a.statcode < b.statcode
              AND  ST_Touches(a.geom, b.geom)
        """)

        count = db.execute("SELECT COUNT(*) FROM neighbors_gemeente").fetchone()[0]
        db.execute("CREATE INDEX IF NOT EXISTS idx_nb_a ON neighbors_gemeente(statcode_a)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_nb_b ON neighbors_gemeente(statcode_b)")
        db.close()

        logger.info("neighbors_gemeente: %d pairs written to gemeente_geo.duckdb", count)
        return count > 0

    except Exception as exc:
        logger.warning("Neighbor computation failed: %s", exc)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Download CBS data to DuckDB")
    parser.add_argument("--tables", nargs="+", metavar="ID", help="Specific table IDs")
    parser.add_argument("--list", action="store_true", help="List stored tables and exit")
    parser.add_argument("--no-geo", action="store_true", help="Skip geometry download")
    parser.add_argument("--geo-year", type=int, default=_GEO_YEAR, help="Boundary year (default: %(default)s)")
    args = parser.parse_args()

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect(str(_DB_PATH))

    if args.list:
        list_local(db)
        db.close()
        return

    target = args.tables if args.tables else list(TABLES.keys())
    for t in target:
        if t not in TABLES:
            TABLES[t] = t

    ok = fail = 0
    for tid in target:
        desc = TABLES[tid]
        if download_table(tid, desc, db):
            record_meta(db, tid, desc)
            ok += 1
        else:
            fail += 1

    db.close()
    size_mb = _DB_PATH.stat().st_size / 1_048_576 if _DB_PATH.exists() else 0
    logger.info("")
    logger.info("Stats: %d OK, %d failed. cijfers.duckdb: %.1f MB", ok, fail, size_mb)

    # Geometry + neighbors
    if not args.no_geo:
        logger.info("")
        geo_ok = download_geometry(year=args.geo_year)
        if geo_ok:
            compute_neighbors_spatial()
            geo_mb = _GEO_DB_PATH.stat().st_size / 1_048_576 if _GEO_DB_PATH.exists() else 0
            logger.info("Geometry: gemeente_geo.duckdb %.1f MB", geo_mb)
        else:
            logger.warning("Geometry download failed — app will fall back to PDOK API")

    if ok > 0:
        logger.info("Backend will use local data (falls back to CBS OData if measure not found).")


if __name__ == "__main__":
    main()
