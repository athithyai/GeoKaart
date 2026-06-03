"""GeoKaart FastAPI application.

Endpoints
---------
GET  /health        → service health check
GET  /catalog       → list of CBS geo-statistical tables
POST /plan          → natural language → MapPlan (no data fetched)
POST /map-data      → MapPlan → enriched GeoJSON
POST /chat          → natural language → MapPlan + enriched GeoJSON + message

The /chat endpoint is the primary integration point for the frontend.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from catalog_index import CatalogIndex, _PRIORITY_TABLES
from cbs_client import get_measure_columns, get_observations
from config import get_settings
from join_engine import join_data_to_geometry
from models import (
    CatalogEntry,
    CatalogResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    MapDataRequest,
    MapDataResponse,
    MapPlan,
    PlanRequest,
)
from planner import generate_narration, generate_plan
import spatial_service
from spatial_service import get_geometries
import duckdb_client
import ingest as _ingest

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()

# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

catalog: CatalogIndex | None = None


async def _warmup_geometry() -> None:
    """Pre-fetch all PDOK geometry collections into cache at startup.

    Runs as a background task so it does not block the first request.
    gemeente  ≈  36 pages × 100 features  →   3 600 features  (~7 s)
    wijk      ≈ 100 pages × 100 features  →  10 000 features  (~20 s)
    buurt     ≈ 800 pages × 100 features  →  80 000 features  (~160 s)
    """
    import asyncio
    for level in ("gemeente", "wijk", "buurt"):
        try:
            logger.info("Geometry warmup: fetching %s …", level)
            await get_geometries(level, None)
            logger.info("Geometry warmup: %s done", level)
        except Exception as exc:
            logger.warning("Geometry warmup failed for %s: %s", level, exc)
        # Small pause between levels to avoid hammering PDOK
        await asyncio.sleep(0.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    global catalog
    logger.info("Building CBS catalog index …")
    catalog = await CatalogIndex.build()
    logger.info("Catalog ready — %d tables indexed", len(catalog.list_tables()))
    # Kick off geometry warmup in background — does not block startup
    asyncio.create_task(_warmup_geometry())
    asyncio.create_task(spatial_service.init_province_map())
    yield
    logger.info("Shutting down GeoKaart backend")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="GeoKaart API",
    description="Conversational geospatial intelligence for the Netherlands — statistics, routing, proximity, timeseries.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request timing middleware ─────────────────────────────────────────────────

@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    response.headers["X-Process-Time"] = f"{elapsed:.3f}s"
    return response


# ── Error handler ─────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)[:200]}"},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

_DEFAULT_MEASURE = "AantalInwoners_5"   # always present in kerncijfers tables

# Measure codes that ONLY exist in 85984NED (2024 kerncijfers).
# If the LLM picks one of these but sets table_id = "86165NED", we hard-correct
# the table before any CBS API call is made — no matter what the LLM said.
_REQUIRES_85984: frozenset[str] = frozenset({
    # Births / deaths / households
    "GeboorteTotaal_25", "SterfteTotaal_27", "HuishoudensTotaal_29",
    # Energy
    "GemiddeldAardgasverbruik_55", "GemiddeldeElektriciteitslevering_53",
    # Education
    "LeerlingenPo_62", "StudentenHbo_65", "StudentenWo_66",
    # Income & wealth
    "GemiddeldInkomenPerInwoner_78", "GemiddeldInkomenPerInkomensontvanger_77",
    "GemGestandaardiseerdInkomen_83", "MediaanVermogenVanParticuliereHuish_86",
    "PersonenInArmoede_81",
    # Social security
    "PersonenPerSoortUitkeringBijstand_87", "PersonenPerSoortUitkeringAO_88",
    "PersonenPerSoortUitkeringWW_89", "PersonenPerSoortUitkeringAOW_90",
    # Care
    "JongerenMetJeugdzorgInNatura_91", "WmoClienten_93",
    # Business
    "BedrijfsvestigingenTotaal_95",
    # Proximity
    "AfstandTotGroteSupermarkt_111", "AfstandTotHuisartsenpraktijk_110",
    "AfstandTotSchool_113", "AfstandTotKinderdagverblijf_112",
})

# OData measure codes that are valid in CBS StatLine but NOT in the local DuckDB
# column index (either partial coverage or completely absent from DuckDB).
# These codes must NEVER be replaced by _fallback_measure — the OData API handles them.
_ODATA_ONLY_CODES: frozenset[str] = frozenset({
    # Proximity measures — OData returns 342 GM rows; DuckDB bulk CSV only 28-44
    "AfstandTotGroteSupermarkt_111",
    "AfstandTotHuisartsenpraktijk_110",
    "AfstandTotSchool_113",
    "AfstandTotKinderdagverblijf_112",
    # Labor measures — CBS publishes null at regional level; let OData confirm that
    "WerkzameBeroepsbevolking_70",
    "Nettoarbeidsparticipatie_71",
    "PercentageZelfstandigen_75",
})

# CBS publishes these measures at gemeente AND buurt level, but NOT wijk level.
# When the planner picks wijk for these, auto-correct to buurt (more granular and
# actually available in the CBS table).
_NOT_WIJK_CODES: dict[str, str] = {
    # Proximity — CBS computes at buurt level only; no wijk aggregation
    "AfstandTotGroteSupermarkt_111":  "buurt",
    "AfstandTotHuisartsenpraktijk_110": "buurt",
    "AfstandTotSchool_113":           "buurt",
    "AfstandTotKinderdagverblijf_112":"buurt",
}

_FALLBACK_MESSAGE = """\
Hmm, ik begreep die vraag niet helemaal. Hier zijn een paar voorbeeldvragen die ik wel begrijp:

**Bevolking & demografie**
- "Toon bevolkingsdichtheid per gemeente"
- "Hoeveel ouderen per buurt in Amsterdam?"

**Wonen & vastgoed**
- "WOZ-waarde per wijk in Utrecht"
- "Percentage koopwoningen per gemeente"

**Inkomen & armoede**
- "Gemiddeld inkomen per inwoner per gemeente"
- "Armoede per buurt in Rotterdam"

**Energie**
- "Gasverbruik per gemeente"
- "Woningen met zonnestroom in Noord-Holland"

**Arbeid & onderwijs**
- "Nettoarbeidsparticipatie per wijk"
- "HBO/WO-opgeleide inwoners per gemeente"

**Nabijheid van voorzieningen**
- "Afstand tot supermarkt per buurt"
- "Afstand tot huisartsenpraktijk per gemeente"

**Zorg & sociale zekerheid**
- "Bijstandsuitkeringen per wijk in Den Haag"
- "Wmo-cliënten per gemeente"

Probeer een van deze vragen, of beschrijf wat je wilt zien op de kaart!\
"""

# Human-readable labels for common measure codes (Dutch)
_MEASURE_LABELS: dict[str, str] = {
    # Bevolking
    "AantalInwoners_5":                       "Aantal inwoners",
    "Bevolkingsdichtheid_33":                 "Bevolkingsdichtheid",
    "Bevolkingsdichtheid_34":                 "Bevolkingsdichtheid",
    "Mannen_6":                               "Mannen",
    "Vrouwen_7":                              "Vrouwen",
    "k_0Tot15Jaar_8":                         "Kinderen (0–15 jaar)",
    "k_65JaarOfOuder_12":                     "Ouderen (65+)",
    "GeboorteTotaal_25":                      "Geboorten",
    "SterfteTotaal_27":                       "Sterfte",
    "HuishoudensTotaal_29":                   "Huishoudens",
    # Wonen
    "GemiddeldeWOZWaardeVanWoningen_39":      "Gemiddelde WOZ-waarde van woningen",
    "Woningvoorraad_35":                      "Woningvoorraad",
    "Koopwoningen_47":                        "Koopwoningen",
    "HuurwoningenTotaal_48":                  "Huurwoningen",
    # Energie
    "GemiddeldAardgasverbruik_55":            "Gemiddeld aardgasverbruik",
    "GemiddeldeElektriciteitslevering_53":    "Gemiddeld elektriciteitsverbruik",
    # Onderwijs
    "LeerlingenPo_62":                        "Leerlingen basisonderwijs",
    "StudentenHbo_65":                        "Studenten hbo",
    "StudentenWo_66":                         "Studenten universiteit",
    # Inkomen
    "GemiddeldInkomenPerInwoner_78":          "Gemiddeld inkomen per inwoner",
    "GemiddeldInkomenPerInkomensontvanger_77":"Gemiddeld inkomen per ontvanger",
    "GemGestandaardiseerdInkomen_83":         "Gestandaardiseerd inkomen",
    "MediaanVermogenVanParticuliereHuish_86": "Mediaan vermogen",
    "PersonenInArmoede_81":                   "Personen in armoede",
    # Sociale zekerheid
    "PersonenPerSoortUitkeringBijstand_87":   "Bijstandsuitkeringen",
    "PersonenPerSoortUitkeringAO_88":         "Arbeidsongeschiktheidsuitkeringen",
    "PersonenPerSoortUitkeringWW_89":         "WW-uitkeringen",
    "PersonenPerSoortUitkeringAOW_90":        "AOW-uitkeringen",
    # Zorg
    "JongerenMetJeugdzorgInNatura_91":        "Jongeren met jeugdzorg",
    "WmoClienten_93":                         "Wmo-cliënten",
    # Bedrijven
    "BedrijfsvestigingenTotaal_95":           "Bedrijfsvestigingen",
    # Motorvoertuigen
    "PersonenautoSTotaal_104":                "Personenauto's",
    "PersonenautoSPerHuishouden_107":         "Personenauto's per huishouden",
    # Nabijheid
    "AfstandTotGroteSupermarkt_111":          "Afstand tot grote supermarkt",
    "AfstandTotHuisartsenpraktijk_110":       "Afstand tot huisartsenpraktijk",
    "AfstandTotSchool_113":                   "Afstand tot basisschool",
    "AfstandTotKinderdagverblijf_112":        "Afstand tot kinderdagverblijf",
    # Oppervlakte
    "OppervlakteTotaal_115":                  "Oppervlakte",
    "Omgevingsadressendichtheid_121":         "Omgevingsadressendichtheid",
    # Legacy / unused
    "Nettoarbeidsparticipatie_71":            "Nettoarbeidsparticipatie",
}

# GM code → city name for the most-queried cities
_GM_NAMES: dict[str, str] = {
    "GM0363": "Amsterdam",   "GM0599": "Rotterdam",  "GM0518": "Den Haag",
    "GM0344": "Utrecht",     "GM0772": "Eindhoven",  "GM0014": "Groningen",
    "GM0855": "Tilburg",     "GM0034": "Almere",     "GM0758": "Breda",
    "GM0268": "Nijmegen",    "GM0153": "Enschede",   "GM0392": "Haarlem",
    "GM0202": "Arnhem",      "GM0307": "Amersfoort", "GM0200": "Apeldoorn",
    "GM0796": "Den Bosch",   "GM0193": "Zwolle",     "GM0546": "Leiden",
    "GM0935": "Maastricht",  "GM0503": "Delft",
}


# ── Related-data connection graph ─────────────────────────────────────────────
# Maps measure_code → list of (label, query_template) for follow-up suggestions.
# Templates use {level} and {location} placeholders filled at runtime.
_RELATED: dict[str, list[tuple[str, str]]] = {
    # Bevolking
    "AantalInwoners_5":          [("Bevolkingsdichtheid", "Bevolkingsdichtheid per {level}{loc}"), ("Gemiddeld inkomen", "Gemiddeld inkomen per inwoner per {level}{loc}"), ("Woningvoorraad", "Woningvoorraad per {level}{loc}")],
    "Bevolkingsdichtheid_34":    [("Aantal inwoners", "Aantal inwoners per {level}{loc}"), ("Woningvoorraad", "Woningvoorraad per {level}{loc}"), ("Afstand tot supermarkt", "Afstand tot supermarkt per {level}{loc}")],
    "k_0Tot15Jaar_8":            [("Leerlingen basisonderwijs", "Leerlingen basisonderwijs per {level}{loc}"), ("Jeugdzorg", "Jongeren met jeugdzorg per {level}{loc}"), ("Afstand tot school", "Afstand tot school per {level}{loc}")],
    "k_65JaarOfOuder_12":        [("AOW-uitkeringen", "AOW-uitkeringen per {level}{loc}"), ("Wmo-cliënten", "Wmo-cliënten per {level}{loc}"), ("Afstand tot huisarts", "Afstand tot huisartsenpraktijk per {level}{loc}")],
    # Wonen
    "GemiddeldeWOZWaardeVanWoningen_39": [("Gemiddeld inkomen", "Gemiddeld inkomen per inwoner per {level}{loc}"), ("Koopwoningen", "Percentage koopwoningen per {level}{loc}"), ("Bevolkingsdichtheid", "Bevolkingsdichtheid per {level}{loc}")],
    "Woningvoorraad_35":         [("WOZ-waarde", "WOZ-waarde per {level}{loc}"), ("Koopwoningen", "Percentage koopwoningen per {level}{loc}"), ("Huurwoningen", "Percentage huurwoningen per {level}{loc}")],
    "Koopwoningen_47":           [("WOZ-waarde", "WOZ-waarde per {level}{loc}"), ("Huurwoningen", "Huurwoningen per {level}{loc}"), ("Mediaan vermogen", "Mediaan vermogen per {level}{loc}")],
    # Energie
    "GemiddeldAardgasverbruik_55":        [("Elektriciteitsverbruik", "Elektriciteitsverbruik per {level}{loc}"), ("Zonnestroom", "Woningen met zonnestroom per {level}{loc}"), ("Woningvoorraad", "Woningvoorraad per {level}{loc}")],
    "GemiddeldeElektriciteitslevering_53":[("Gasverbruik", "Gasverbruik per {level}{loc}"), ("Zonnestroom", "Woningen met zonnestroom per {level}{loc}"), ("WOZ-waarde", "WOZ-waarde per {level}{loc}")],
    "WoningenMetZonnestroom_59":          [("Gasverbruik", "Gasverbruik per {level}{loc}"), ("Elektriciteitsverbruik", "Elektriciteitsverbruik per {level}{loc}"), ("WOZ-waarde", "WOZ-waarde per {level}{loc}")],
    # Inkomen
    "GemiddeldInkomenPerInwoner_78":      [("WOZ-waarde", "WOZ-waarde per {level}{loc}"), ("Armoede", "Armoede per {level}{loc}"), ("Nettoarbeidsparticipatie", "Nettoarbeidsparticipatie per {level}{loc}")],
    "PersonenInArmoede_81":               [("Gemiddeld inkomen", "Gemiddeld inkomen per inwoner per {level}{loc}"), ("Bijstand", "Bijstandsuitkeringen per {level}{loc}"), ("WW-uitkeringen", "WW-uitkeringen per {level}{loc}")],
    "MediaanVermogenVanParticuliereHuish_86": [("Gemiddeld inkomen", "Gemiddeld inkomen per inwoner per {level}{loc}"), ("WOZ-waarde", "WOZ-waarde per {level}{loc}"), ("Koopwoningen", "Koopwoningen per {level}{loc}")],
    # Arbeid
    "Nettoarbeidsparticipatie_71":        [("Gemiddeld inkomen", "Gemiddeld inkomen per inwoner per {level}{loc}"), ("HBO/WO-opgeleiden", "HBO/WO-opgeleiden per {level}{loc}"), ("Bedrijfsvestigingen", "Bedrijfsvestigingen per {level}{loc}")],
    "WerkzameBeroepsbevolking_70":        [("Nettoarbeidsparticipatie", "Nettoarbeidsparticipatie per {level}{loc}"), ("Bijstand", "Bijstand per {level}{loc}"), ("Bedrijfsvestigingen", "Bedrijfsvestigingen per {level}{loc}")],
    # Sociale zekerheid
    "PersonenPerSoortUitkeringBijstand_87": [("Armoede", "Armoede per {level}{loc}"), ("WW-uitkeringen", "WW-uitkeringen per {level}{loc}"), ("Gemiddeld inkomen", "Gemiddeld inkomen per {level}{loc}")],
    "PersonenPerSoortUitkeringWW_89":       [("Bijstand", "Bijstand per {level}{loc}"), ("Nettoarbeidsparticipatie", "Nettoarbeidsparticipatie per {level}{loc}"), ("Armoede", "Armoede per {level}{loc}")],
    # Zorg
    "JongerenMetJeugdzorgInNatura_91":    [("Jongeren 0-15 jaar", "Percentage jongeren per {level}{loc}"), ("Afstand tot school", "Afstand tot school per {level}{loc}"), ("Bijstand", "Bijstand per {level}{loc}")],
    "WmoClienten_93":                     [("Ouderen 65+", "Percentage ouderen per {level}{loc}"), ("AOW-uitkeringen", "AOW-uitkeringen per {level}{loc}"), ("Afstand tot huisarts", "Afstand tot huisartsenpraktijk per {level}{loc}")],
    # Bedrijven
    "BedrijfsvestigingenTotaal_95":       [("Werkzame beroepsbevolking", "Werkzame beroepsbevolking per {level}{loc}"), ("Gemiddeld inkomen", "Gemiddeld inkomen per {level}{loc}"), ("Bevolkingsdichtheid", "Bevolkingsdichtheid per {level}{loc}")],
    # Nabijheid
    "AfstandTotGroteSupermarkt_111":      [("Afstand tot huisarts", "Afstand tot huisartsenpraktijk per {level}{loc}"), ("Afstand tot school", "Afstand tot school per {level}{loc}"), ("Bevolkingsdichtheid", "Bevolkingsdichtheid per {level}{loc}")],
    "AfstandTotHuisartsenpraktijk_110":   [("Afstand tot supermarkt", "Afstand tot supermarkt per {level}{loc}"), ("Ouderen 65+", "Percentage ouderen per {level}{loc}"), ("Wmo-cliënten", "Wmo-cliënten per {level}{loc}")],
    "AfstandTotSchool_113":               [("Leerlingen basisonderwijs", "Leerlingen basisonderwijs per {level}{loc}"), ("Afstand tot kinderdagverblijf", "Afstand tot kinderdagverblijf per {level}{loc}"), ("Jongeren 0-15", "Jongeren 0-15 jaar per {level}{loc}")],
}

def _make_suggestions(plan: "MapPlan") -> list[str]:
    """Return 2–3 related follow-up query strings based on current measure."""
    pairs = _RELATED.get(plan.measure_code, [])
    if not pairs:
        return []
    level = plan.geography_level
    loc   = f" in {_GM_NAMES[plan.region_scope]}" if plan.region_scope and plan.region_scope in _GM_NAMES else ""
    return [tmpl.format(level=level, loc=loc) for _, tmpl in pairs[:3]]


def _build_message(plan: "MapPlan", meta: dict | None = None) -> str:
    """Generate a readable Dutch assistant message from the plan + optional join stats."""
    measure  = _MEASURE_LABELS.get(plan.measure_code, plan.measure_code.replace("_", " "))
    level    = plan.geography_level
    scope    = plan.region_scope
    location = _GM_NAMES.get(scope, scope) if scope else "Nederland"

    base = f"{measure} per {level} in {location}."

    if meta:
        n_matched = meta.get("n_matched", 0)
        n_total   = meta.get("n_total", 0)
        breaks    = meta.get("breaks", [])

        if n_matched > 0 and len(breaks) >= 2:
            lo  = breaks[0]
            hi  = breaks[-1]

            def fmt(v: float) -> str:
                if abs(v) >= 1_000_000:
                    return f"{v/1_000_000:.1f}M"
                if abs(v) >= 1_000:
                    return f"{v:,.0f}".replace(",", "\u202f")
                if v != int(v):
                    return f"{v:.1f}"
                return str(int(v))

            coverage = ""
            if n_matched < n_total:
                coverage = f" ({n_matched} van {n_total} regio's hebben data)"

            return (
                f"{base}\n"
                f"Bereik: {fmt(lo)} – {fmt(hi)}{coverage}."
            )

        if n_matched == 0:
            return f"{base}\nGeen data beschikbaar voor deze selectie."

    return base

def _fallback_measure(requested: str, available: set[str]) -> str:
    """Return the closest available measure or the safe default."""
    # Try a prefix match (e.g. LLM stripped a suffix number)
    prefix = requested.split("_")[0].lower()
    for code in sorted(available):
        if code.lower().startswith(prefix):
            return code
    return _DEFAULT_MEASURE


def _extract_context_from_history(history: list[dict[str, str]]) -> dict | None:
    """Parse the last assistant message that contains map context metadata.

    chatStore.ts appends a suffix to assistant messages:
      "(Map context: level=buurt, scope=GM0344, measure=GemiddeldeWOZWaardeVanWoningen_39, table=86165NED)"
    """
    import re as _re
    pattern = _re.compile(
        r"\(Map context: level=(\w+), scope=([^,]+), measure=([^,]+), table=([^)]+)\)"
    )
    for turn in reversed(history):
        if turn.get("role") != "assistant":
            continue
        m = pattern.search(turn.get("content", ""))
        if m:
            scope_raw = m.group(2).strip()
            return {
                "geography_level": m.group(1).strip(),
                "region_scope": None if scope_raw in ("None", "null", "all Netherlands") else scope_raw,
                "measure_code": m.group(3).strip(),
                "table_id": m.group(4).strip(),
            }
    return None


_CITY_TO_GM: dict[str, str] = {
    "amsterdam": "GM0363", "rotterdam": "GM0599", "den haag": "GM0518",
    "the hague": "GM0518", "utrecht": "GM0344", "eindhoven": "GM0772",
    "groningen": "GM0014", "tilburg": "GM0855", "almere": "GM0034",
    "breda": "GM0758", "nijmegen": "GM0268", "enschede": "GM0153",
    "haarlem": "GM0392", "arnhem": "GM0202", "amersfoort": "GM0307",
    "apeldoorn": "GM0200", "den bosch": "GM0796", "zwolle": "GM0193",
    "leiden": "GM0546", "maastricht": "GM0935", "delft": "GM0503",
    "dordrecht": "GM0505", "zoetermeer": "GM0637", "deventer": "GM0150",
    "alkmaar": "GM0361", "leeuwarden": "GM0080", "venlo": "GM0983",
}


import re as _re

# Patterns that unambiguously signal a buffer/comparison query.
# Matched against the full user message (which includes [Selected region: ...] context).
_BUFFER_SIGNALS: list[_re.Pattern] = [
    # Dutch: "vergelijk X met andere/omliggende/naburige gemeenten/wijken/buurten"
    _re.compile(r"vergelijk\s+(.+?)\s+met\s+(?:andere|omliggende|naburige|omringende)", _re.I),
    # Dutch: "X en omgeving" / "X eo"
    _re.compile(r"([\w\s\-]+?)\s+(?:en\s+omgeving|eo)\b", _re.I),
    # Dutch: "(de\s+)?omgeving van X" / "omliggende X"
    _re.compile(r"(?:de\s+)?omgeving\s+(?:van\s+)?([\w\s\-]+)", _re.I),
    # Dutch: "omliggende gemeenten/wijken/buurten"  (center from selected region context)
    _re.compile(r"omliggende\s+(?:gemeenten|wijken|buurten|gebieden)", _re.I),
    # English: "compare X with other/surrounding/nearby"
    _re.compile(r"compare\s+(.+?)\s+with\s+(?:other|surrounding|nearby)", _re.I),
    # English: "surrounding (areas of) X"
    _re.compile(r"surrounding\s+(?:areas?\s+of\s+)?([\w\s\-]+)", _re.I),
]

# Match [Selected region: NAME (CODE)] from the contextual text
_SELECTED_RE = _re.compile(r"\[Selected region:\s*([^\(]+)\s*\(([A-Z0-9]+)", _re.I)


def _infer_buffer_scope(message: str, plan: "MapPlan") -> "MapPlan":
    """Post-hoc buffer detection when the LLM missed the buffer trigger.

    If the message matches a comparison pattern but buffer_scope is not set,
    this function infers the center region from the message text or the
    [Selected region: NAME (CODE)] annotation appended by the frontend.
    """
    if plan.buffer_scope:
        return plan  # Already set — nothing to do

    msg = message
    is_buffer_query = any(p.search(msg) for p in _BUFFER_SIGNALS)
    if not is_buffer_query:
        return plan

    # Try to find the center region name
    center: str | None = None

    # 1. Try to extract from [Selected region: NAME (CODE)]
    sel_match = _SELECTED_RE.search(msg)
    if sel_match:
        center = sel_match.group(1).strip()

    # 2. Try the first capture group from Dutch/English comparison patterns
    if not center:
        for pat in _BUFFER_SIGNALS:
            m = pat.search(msg)
            if m and m.lastindex and m.lastindex >= 1:
                candidate = m.group(1).strip()
                # Skip fragments that are clearly not region names
                if len(candidate) >= 2 and candidate.lower() not in (
                    "de", "het", "een", "the", "a", "an", "andere", "omliggende"
                ):
                    center = candidate
                    break

    if not center:
        return plan

    km_map = {"gemeente": 50, "wijk": 20, "buurt": 10}
    km = km_map.get(plan.geography_level, 50)
    logger.info(
        "Buffer inferred from message pattern: center=%r km=%d (LLM had buffer_scope=null)",
        center, km,
    )
    return plan.model_copy(update={
        "buffer_scope": center,
        "buffer_km": float(km),
        "region_scope": None,
    })


_PROVINCE_NAMES: frozenset[str] = frozenset({
    "groningen", "friesland", "fryslân", "drenthe", "overijssel", "flevoland",
    "gelderland", "utrecht", "noord-holland", "noord holland", "south holland",
    "zuid-holland", "zuid holland", "zeeland", "noord-brabant", "noord brabant",
    "limburg",
})

_PROVINCE_CANONICAL: dict[str, str] = {
    "friesland": "Friesland", "fryslân": "Friesland",
    "groningen": "Groningen", "drenthe": "Drenthe",
    "overijssel": "Overijssel", "flevoland": "Flevoland",
    "gelderland": "Gelderland", "utrecht": "Utrecht",
    "noord-holland": "Noord-Holland", "noord holland": "Noord-Holland",
    "south holland": "Zuid-Holland",
    "zuid-holland": "Zuid-Holland", "zuid holland": "Zuid-Holland",
    "zeeland": "Zeeland",
    "noord-brabant": "Noord-Brabant", "noord brabant": "Noord-Brabant",
    "limburg": "Limburg",
}


def _correct_region_scope(message: str, plan: "MapPlan") -> "MapPlan":
    """Post-hoc correction of region/province scope.

    1. For wijk/buurt: province_scope is meaningless — clear it and use a city GM code.
    2. For gemeente: if a province name is in the message, set province_scope.
    3. For gemeente: if a city name is in the message, set region_scope.
    """
    lower = message.lower()

    # ── wijk / buurt: province filtering doesn't apply — need a GM region_scope ──
    if plan.geography_level in ("wijk", "buurt"):
        updates: dict = {}
        if plan.province_scope:
            updates["province_scope"] = None  # province_scope has no effect at wijk/buurt level
        if not plan.region_scope:
            for city, code in _CITY_TO_GM.items():
                if city in lower:
                    logger.info(
                        "wijk/buurt scope: resolved '%s' → region_scope '%s'", city, code
                    )
                    updates["region_scope"] = code
                    break
        if updates:
            plan = plan.model_copy(update=updates)
        return plan

    # ── gemeente: province wins over city (province shows all municipalities in it) ──
    if plan.province_scope is None:
        for alias, canonical in _PROVINCE_CANONICAL.items():
            if alias in lower:
                if plan.province_scope != canonical:
                    logger.info("Correcting province_scope None → '%s'", canonical)
                    plan = plan.model_copy(update={
                        "province_scope": canonical,
                        "region_scope": None,
                    })
                break

    # City correction (only if no province scope was just set)
    if plan.province_scope is None:
        for city, code in _CITY_TO_GM.items():
            if city not in lower:
                continue
            if plan.region_scope != code:
                logger.warning(
                    "Correcting region_scope '%s' → '%s' (city '%s' in message)",
                    plan.region_scope, code, city,
                )
                return plan.model_copy(update={"region_scope": code})
            break

    return plan


def _extract_top_regions(enriched: dict, n: int = 5) -> list[dict]:
    """Return the top N features by value from an enriched GeoJSON."""
    features = enriched.get("features", [])
    with_values = [
        {
            "statcode": f["properties"].get("statcode", ""),
            "statnaam": f["properties"].get("statnaam", ""),
            "value": f["properties"].get("value"),
        }
        for f in features
        if f.get("properties", {}).get("value") is not None
    ]
    return sorted(with_values, key=lambda r: r["value"], reverse=True)[:n]


def _require_catalog() -> CatalogIndex:
    if catalog is None:
        raise HTTPException(status_code=503, detail="Catalog not yet initialised; try again shortly.")
    return catalog


async def _execute_plan(plan: MapPlan) -> tuple[dict[str, Any], list[str]]:
    """Run a MapPlan end-to-end and return (enriched_geojson, warnings)."""
    all_warnings: list[str] = []

    # 1. Fetch CBS observations
    try:
        df = await get_observations(
            table_id=plan.table_id,
            measure_code=plan.measure_code,
            geography_level=plan.geography_level,
            region_scope=plan.region_scope,
            period=plan.period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if df.empty:
        all_warnings.append(
            f"No data returned for measure '{plan.measure_code}' in table '{plan.table_id}'. "
            "Check that the measure code is valid."
        )

    # 2. Fetch PDOK geometry
    try:
        geojson = await get_geometries(
            geo_level=plan.geography_level,
            region_scope=plan.region_scope,
            province_scope=plan.province_scope,
            buffer_scope=plan.buffer_scope,
            buffer_km=plan.buffer_km,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if not geojson.get("features"):
        all_warnings.append("No boundary geometries returned from PDOK.")

    # 3. Join CBS data with geometry
    enriched, join_warnings = join_data_to_geometry(
        geojson=geojson,
        df=df,
        measure_code=plan.measure_code,
        classification=plan.classification,
        n_classes=plan.n_classes,
    )
    all_warnings.extend(join_warnings)

    return enriched, all_warnings


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health():
    return HealthResponse()


@app.get("/catalog", response_model=CatalogResponse, tags=["catalog"])
async def get_catalog():
    """List available CBS geo-statistical tables."""
    cat = _require_catalog()
    entries = [
        CatalogEntry(
            id=t.id,
            title=t.title,
            period=t.period,
            geo_levels=t.geo_levels,
        )
        for t in cat.list_tables()
    ]
    return CatalogResponse(tables=entries)


@app.post("/plan", response_model=MapPlan, tags=["planning"])
async def plan_endpoint(body: PlanRequest):
    """Convert a natural-language message to a structured MapPlan (no data fetched)."""
    cat = _require_catalog()
    try:
        plan = await generate_plan(body.message, body.history, cat)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return plan


@app.get("/boundaries", tags=["data"])
async def boundaries_endpoint(
    level: str = "gemeente",
    scope: str | None = None,
):
    """Return PDOK boundary geometry only — no CBS data, no choropleth colours.

    Fast: geometry is cached 24 h after the first fetch.
    Used by the layer-toggle buttons on the map.
    """
    if level not in ("gemeente", "wijk", "buurt"):
        raise HTTPException(status_code=422, detail="level must be gemeente, wijk or buurt")
    try:
        geojson = await get_geometries(geo_level=level, region_scope=scope or None)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return geojson


@app.get("/search", tags=["data"])
async def search_endpoint(q: str = "", limit: int = 12):
    """Search for regions by name across all geography levels.

    Returns immediately with whatever is cached; empty if geometry not yet loaded.
    """
    if len(q.strip()) < 2:
        return {"results": []}
    results = spatial_service.search_regions(q.strip(), limit=limit)
    return {"results": results}


@app.post("/map-data", response_model=MapDataResponse, tags=["data"])
async def map_data_endpoint(body: MapDataRequest):
    """Execute a MapPlan and return enriched GeoJSON."""
    enriched, warnings = await _execute_plan(body.plan)
    return MapDataResponse(
        geojson=enriched,
        message=body.plan.message,
        warnings=warnings,
    )


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat_endpoint(body: ChatRequest):
    """Primary chat endpoint: NL message → plan + enriched GeoJSON + assistant message.

    Flow
    ----
    1. Extract current map context from history (for carry-over)
    2. Generate MapPlan from LLM (with context)
    3. Route by intent:
       - info    → return plan.message directly, no data fetch
       - explain → call Narrator with history context, no data fetch
       - map_choropleth → fetch CBS + PDOK + join, then call Narrator
    4. Return ChatResponse with conversational reply
    """
    cat = _require_catalog()

    # Step 1: Extract current map context from chat history for LLM carry-over
    context = _extract_context_from_history(body.history)

    # Step 2: Plan — catch failures gracefully (never return a 422 for chat)
    try:
        plan = await generate_plan(body.message, body.history, cat, context=context, lang=body.lang)
    except ValueError as exc:
        logger.warning("Planning failed: %s", exc)
        fallback_plan = MapPlan(
            intent="info",
            table_id=settings.DEFAULT_TABLE,
            measure_code=_DEFAULT_MEASURE,
            geography_level="gemeente",
            region_scope=None,
            period=None,
            classification="quantile",
            n_classes=5,
            message="Sorry, I didn't quite understand that.",
        )
        return ChatResponse(
            message=_FALLBACK_MESSAGE,
            plan=fallback_plan,
            geojson={"type": "FeatureCollection", "features": []},
            warnings=[],
        )

    # Guard: only allow priority (kerncijfers) tables
    if plan.table_id not in _PRIORITY_TABLES:
        logger.warning(
            "LLM chose non-priority table '%s'; falling back to %s",
            plan.table_id, settings.DEFAULT_TABLE,
        )
        plan = plan.model_copy(update={"table_id": settings.DEFAULT_TABLE})

    logger.info(
        "Plan: table=%s measure=%s level=%s scope=%s intent=%s",
        plan.table_id, plan.measure_code, plan.geography_level,
        plan.region_scope, plan.intent,
    )

    # Correct region_scope against city names in the message (fixes model hallucinations)
    plan = _correct_region_scope(body.message, plan)

    # Infer buffer scope when LLM missed a comparison/surrounding pattern
    plan = _infer_buffer_scope(body.message, plan)

    # Safety net: if buffer_scope is active (set by LLM or inferred), region_scope
    # MUST be None — otherwise get_geometries scopes to just one polygon instead
    # of fetching all surrounding regions for the buffer to filter.
    if plan.buffer_scope and plan.region_scope:
        logger.info(
            "Clearing region_scope=%r — buffer_scope=%r takes precedence",
            plan.region_scope, plan.buffer_scope,
        )
        plan = plan.model_copy(update={"region_scope": None})

    if plan.buffer_scope:
        logger.info("Buffer scope active: center=%r km=%.0f", plan.buffer_scope, plan.buffer_km)

    measure_label = _MEASURE_LABELS.get(plan.measure_code, plan.measure_code.replace("_", " "))

    # ── Info intent: return the planner's message directly — no Narrator call.
    # The Narrator has no CBS data context here and would hallucinate facts.
    if plan.intent == "info":
        logger.info("Info intent — returning planner message directly")
        return ChatResponse(
            message=plan.message,
            plan=plan,
            geojson={"type": "FeatureCollection", "features": []},
            warnings=[],
        )

    # ── Explain intent: narrate from history context, no CBS/PDOK fetch ───────
    if plan.intent == "explain":
        logger.info("Explain intent — calling Narrator without data fetch")
        reply = await generate_narration(
            user_message=body.message,
            plan=plan,
            meta=None,
            history=body.history,
            measure_label=measure_label,
            top_regions=None,
            lang=body.lang,
        )
        return ChatResponse(
            message=reply,
            plan=plan,
            geojson={"type": "FeatureCollection", "features": []},
            warnings=[],
        )

    # ── Map choropleth: validate measure, fetch CBS + PDOK + join, narrate ──────

    # Auto-correct geography_level when CBS doesn't publish this measure at wijk level.
    # E.g. proximity measures exist at buurt/gemeente but NOT wijk — switch to buurt.
    if plan.geography_level == "wijk" and plan.measure_code in _NOT_WIJK_CODES:
        corrected_level = _NOT_WIJK_CODES[plan.measure_code]
        logger.info(
            "Level corrected: wijk → %s (measure '%s' not available at wijk level)",
            corrected_level, plan.measure_code,
        )
        plan = plan.model_copy(update={"geography_level": corrected_level})

    # Hard-correct table_id when the LLM picks a measure that only exists in 85984NED.
    # This overrides any hallucinated table_id before any CBS API call is made.
    if plan.measure_code in _REQUIRES_85984 and plan.table_id != "85984NED":
        logger.info(
            "table_id corrected: '%s' → '85984NED' (measure '%s' requires 2024 table)",
            plan.table_id, plan.measure_code,
        )
        plan = plan.model_copy(update={"table_id": "85984NED"})

    # Only validate measure_code for map queries (skipped for info/explain)
    try:
        valid_codes = {m["code"] for m in await get_measure_columns(plan.table_id)}
        if valid_codes and plan.measure_code not in valid_codes:
            if plan.measure_code in _ODATA_ONLY_CODES:
                # Valid OData code that DuckDB doesn't index — trust the planner
                logger.info(
                    "measure_code '%s' not in DuckDB index but is a known OData code — keeping",
                    plan.measure_code,
                )
            else:
                fallback = _fallback_measure(plan.measure_code, valid_codes)
                logger.warning(
                    "measure_code '%s' not in table %s; using '%s'",
                    plan.measure_code, plan.table_id, fallback,
                )
                plan = plan.model_copy(update={"measure_code": fallback})
    except Exception as exc:
        logger.warning("Could not validate measure_code: %s", exc)

    # Pass region_scope through unchanged so the map is always scoped to exactly
    # what was asked:
    #   - gemeente + GM scope  → just that single municipality
    #   - wijk/buurt + GM scope → all districts/neighbourhoods in that municipality
    #   - buffer_scope set      → spatial buffer handles filtering; region_scope is null
    #   - no scope              → all Netherlands
    fetch_scope = plan.region_scope

    enriched: dict = {"type": "FeatureCollection", "features": []}
    warnings: list[str] = []
    meta: dict | None = None
    top_regions: list[dict] = []

    try:
        enriched, warnings = await _execute_plan(
            plan.model_copy(update={"region_scope": fetch_scope})
        )
        meta = enriched.get("meta") if isinstance(enriched, dict) else None
        top_regions = _extract_top_regions(enriched)
    except HTTPException as exc:
        logger.warning("Data fetch failed (HTTP %s): %s", exc.status_code, exc.detail)
        warnings.append(f"Could not load map data: {exc.detail}")
        # Fall through to Narrator — it will explain gracefully with meta=None

    # For buffer queries: find the center region's value so narrator can compare
    center_value: float | None = None
    if plan.buffer_scope:
        bs_upper = plan.buffer_scope.strip().upper()
        bs_lower = plan.buffer_scope.strip().lower()
        for f in enriched.get("features", []):
            props = f.get("properties", {})
            sc = str(props.get("statcode", "")).strip().upper()
            sn = str(props.get("statnaam", "")).strip().lower()
            if sc == bs_upper or sn == bs_lower:
                center_value = props.get("value")
                break

    # Call Narrator for a rich conversational reply
    reply = await generate_narration(
        user_message=body.message,
        plan=plan,
        meta=meta,
        history=body.history,
        measure_label=measure_label,
        top_regions=top_regions or None,
        center_value=center_value if plan.buffer_scope else None,
        lang=body.lang,
    )

    return ChatResponse(
        message=reply,
        plan=plan,
        geojson=enriched,
        warnings=warnings,
        suggestions=_make_suggestions(plan),
    )


# ── Admin endpoints ────────────────────────────────────────────────────────────

async def _run_ingest_task() -> None:
    """Background task wrapper — manages spatial DuckDB connection lifecycle."""
    # Close the read connection BEFORE writing to avoid file-lock issues on Windows
    duckdb_client.invalidate_spatial_conn()
    try:
        await _ingest.run_ingest()
    finally:
        # Force reconnect so the next spatial query picks up the freshly rebuilt file
        duckdb_client.invalidate_spatial_conn()


@app.post("/admin/ingest", tags=["admin"])
async def admin_ingest(background_tasks: BackgroundTasks):
    """Trigger a background rebuild of cbs_spatial.duckdb.

    Downloads all CBS kerncijfers data for gemeente/wijk/buurt, computes
    shared-boundary adjacency, and writes the preprocessed database.
    Takes 5–15 minutes depending on network speed.  Poll /admin/status.
    """
    status = _ingest.get_status()
    if status["status"] == "running":
        return {"status": "already_running", "progress": status.get("progress", "")}
    background_tasks.add_task(_run_ingest_task)
    return {"status": "started"}


@app.get("/admin/status", tags=["admin"])
async def admin_status():
    """Return the current ingest pipeline status.

    Combines live run-state (from ingest.py) with the last persisted log entry
    (from cbs_spatial.duckdb) so the frontend always gets a useful timestamp.
    """
    live = _ingest.get_status()

    # Augment with last persisted log entry when idle
    if live["status"] in ("idle", "done", "error"):
        db_log = duckdb_client.get_ingest_status()
        if db_log:
            live["db_log"] = db_log

    live["spatial_db_available"] = duckdb_client.is_spatial_available()
    return live
