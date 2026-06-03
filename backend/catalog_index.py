"""CBS StatLine catalog index.

Builds an in-memory lookup of available CBS tables filtered for
geo-statistical relevance (wijken/buurten/kerncijfers).

Usage
-----
    index = await CatalogIndex.build()
    table_id = index.find_table("population", "gemeente")
    measures  = await index.get_measures("86165NED")
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from cache import cache_get, cache_set, make_key, metadata_cache
from cbs_client import get_measure_columns
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# CBS tables known to contain wijk/buurt kerncijfers — checked first
# 86165NED (2025): demographics, housing, vehicles, area
# 85984NED (2024): ALL categories — energy, labor, income, social, care, business, proximity
_PRIORITY_TABLES = ["86165NED", "85984NED", "85618NED", "84799NED"]

# Verified measure codes — cross-referenced against CBS OData DataProperties.
# Covers all 12 CBS categories shown on the data portal.
# Used as fallback hints when the LLM needs guidance.
_TOPIC_HINTS: dict[str, list[str]] = {
    # ── Bevolking (86165NED) ───────────────────────────────────────────────────
    "population":       ["AantalInwoners_5"],
    "bevolking":        ["AantalInwoners_5"],
    "inwoners":         ["AantalInwoners_5"],
    "density":          ["Bevolkingsdichtheid_34"],
    "dichtheid":        ["Bevolkingsdichtheid_34"],
    "men":              ["Mannen_6"],
    "mannen":           ["Mannen_6"],
    "women":            ["Vrouwen_7"],
    "vrouwen":          ["Vrouwen_7"],
    "youth":            ["k_0Tot15Jaar_8"],
    "jongeren":         ["k_0Tot15Jaar_8"],
    "elderly":          ["k_65JaarOfOuder_12"],
    "ouderen":          ["k_65JaarOfOuder_12"],
    "geboorte":         ["GeboorteTotaal_25"],       # 85984NED code
    "births":           ["GeboorteTotaal_25"],
    "sterfte":          ["SterfteTotaal_27"],         # 85984NED code
    "deaths":           ["SterfteTotaal_27"],
    "households":       ["HuishoudensTotaal_29"],     # 85984NED code
    "huishoudens":      ["HuishoudensTotaal_29"],
    # ── Wonen en vastgoed (86165NED / 85984NED) ───────────────────────────────
    "house":            ["GemiddeldeWOZWaardeVanWoningen_39"],
    "woz":              ["GemiddeldeWOZWaardeVanWoningen_39"],
    "woningwaarde":     ["GemiddeldeWOZWaardeVanWoningen_39"],
    "huiswaarde":       ["GemiddeldeWOZWaardeVanWoningen_39"],
    "vastgoed":         ["GemiddeldeWOZWaardeVanWoningen_39"],
    "woningen":         ["Woningvoorraad_35"],
    "housing":          ["Woningvoorraad_35"],
    "koopwoning":       ["Koopwoningen_47"],
    "huurwoning":       ["HuurwoningenTotaal_48"],
    # ── Energie (85984NED) ────────────────────────────────────────────────────
    "energie":          ["GemiddeldeElektriciteitslevering_53"],
    "energy":           ["GemiddeldeElektriciteitslevering_53"],
    "elektriciteit":    ["GemiddeldeElektriciteitslevering_53"],
    "electricity":      ["GemiddeldeElektriciteitslevering_53"],
    "gas":              ["GemiddeldAardgasverbruik_55"],
    "gasverbruik":      ["GemiddeldAardgasverbruik_55"],
    # zonnestroom → not available at regional level (CBS suppresses this data)
    "zonnestroom":      ["GemiddeldeElektriciteitslevering_53"],
    "solar":            ["GemiddeldeElektriciteitslevering_53"],
    # ── Onderwijs (85984NED) ──────────────────────────────────────────────────
    "onderwijs":        ["StudentenHbo_65"],
    "education":        ["StudentenHbo_65"],
    "leerlingen":       ["LeerlingenPo_62"],
    "students":         ["LeerlingenPo_62"],
    "hbo":              ["StudentenHbo_65"],
    "university":       ["StudentenWo_66"],
    # ── Arbeid (85984NED) — NOT AVAILABLE: CBS publishes null at regional level ─
    # Redirect to income / businesses as best available proxy
    "arbeid":           ["GemiddeldInkomenPerInwoner_78"],
    "werkenden":        ["GemiddeldInkomenPerInwoner_78"],
    "labor":            ["GemiddeldInkomenPerInwoner_78"],
    "work":             ["GemiddeldInkomenPerInwoner_78"],
    "employment":       ["GemiddeldInkomenPerInwoner_78"],
    "werkgelegenheid":  ["BedrijfsvestigingenTotaal_95"],
    "zelfstandigen":    ["BedrijfsvestigingenTotaal_95"],
    # ── Inkomen (85984NED) ────────────────────────────────────────────────────
    "income":           ["GemiddeldInkomenPerInwoner_78"],
    "inkomen":          ["GemiddeldInkomenPerInwoner_78"],
    "salaris":          ["GemiddeldInkomenPerInwoner_78"],
    "wealthy":          ["GemiddeldInkomenPerInwoner_78"],
    "armoede":          ["PersonenInArmoede_81"],
    "poverty":          ["PersonenInArmoede_81"],
    "vermogen":         ["MediaanVermogenVanParticuliereHuish_86"],
    # ── Sociale zekerheid (85984NED) ──────────────────────────────────────────
    "uitkering":        ["PersonenPerSoortUitkeringBijstand_87"],
    "welfare":          ["PersonenPerSoortUitkeringBijstand_87"],
    "bijstand":         ["PersonenPerSoortUitkeringBijstand_87"],
    "ao":               ["PersonenPerSoortUitkeringAO_88"],
    "ww":               ["PersonenPerSoortUitkeringWW_89"],
    "aow":              ["PersonenPerSoortUitkeringAOW_90"],
    # ── Zorg (85984NED) ───────────────────────────────────────────────────────
    "zorg":             ["JongerenMetJeugdzorgInNatura_91"],
    "jeugdzorg":        ["JongerenMetJeugdzorgInNatura_91"],
    "wmo":              ["WmoClienten_93"],
    "care":             ["JongerenMetJeugdzorgInNatura_91"],
    # ── Bedrijfsvestigingen (85984NED) ────────────────────────────────────────
    "bedrijven":        ["BedrijfsvestigingenTotaal_95"],
    "vestigingen":      ["BedrijfsvestigingenTotaal_95"],
    "business":         ["BedrijfsvestigingenTotaal_95"],
    "companies":        ["BedrijfsvestigingenTotaal_95"],
    # ── Motorvoertuigen (86165NED) ────────────────────────────────────────────
    "auto":             ["PersonenautoSTotaal_104"],
    "cars":             ["PersonenautoSTotaal_104"],
    "voertuigen":       ["PersonenautoSTotaal_104"],
    "personenauto":     ["PersonenautoSTotaal_104"],
    # ── Nabijheid (85984NED) ──────────────────────────────────────────────────
    "supermarkt":       ["AfstandTotGroteSupermarkt_111"],
    "supermarket":      ["AfstandTotGroteSupermarkt_111"],
    "huisarts":         ["AfstandTotHuisartsenpraktijk_110"],
    "doctor":           ["AfstandTotHuisartsenpraktijk_110"],
    "basisschool":      ["AfstandTotSchool_113"],
    "school":           ["AfstandTotSchool_113"],
    "kinderdagverblijf":["AfstandTotKinderdagverblijf_112"],
    "nabijheid":        ["AfstandTotGroteSupermarkt_111"],
    "proximity":        ["AfstandTotGroteSupermarkt_111"],
    # ── Oppervlakte (86165NED) ────────────────────────────────────────────────
    "oppervlakte":      ["OppervlakteTotaal_115"],
    "area":             ["OppervlakteTotaal_115"],
    "omgevingsadres":   ["Omgevingsadressendichtheid_121"],
    "oad":              ["Omgevingsadressendichtheid_121"],
    "urban":            ["Omgevingsadressendichtheid_121"],
    "stedelijk":        ["Omgevingsadressendichtheid_121"],
}


@dataclass
class TableMeta:
    id: str
    title: str
    short_title: str
    period: str
    geo_levels: list[str] = field(default_factory=list)


class CatalogIndex:
    """In-memory index of CBS geo-statistical tables."""

    def __init__(self, tables: list[TableMeta], measures: dict[str, list[dict[str, str]]]) -> None:
        self._tables = tables
        self._measures = measures  # table_id → [{code, title, unit}]

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    async def build(cls) -> "CatalogIndex":
        """Fetch CBS catalog and build the index. Cached for CACHE_TTL_METADATA seconds."""
        cache_key = make_key("catalog_index")
        if cached := cache_get(metadata_cache, cache_key):
            logger.debug("Returning cached catalog index")
            tables_raw, measures_raw = cached
            tables = [TableMeta(**t) for t in tables_raw]
            return cls(tables, measures_raw)

        logger.info("Building CBS catalog index …")
        tables = await _fetch_geo_tables()
        measures: dict[str, list[dict[str, str]]] = {}

        # Pre-fetch measures for priority tables
        for tid in _PRIORITY_TABLES:
            if any(t.id == tid for t in tables):
                try:
                    measures[tid] = await get_measure_columns(tid)
                except Exception as exc:
                    logger.warning("Could not fetch measures for %s: %s", tid, exc)

        cache_set(
            metadata_cache,
            cache_key,
            ([t.__dict__ for t in tables], measures),
        )
        logger.info("Catalog index built: %d tables", len(tables))
        return cls(tables, measures)

    # ── Public API ────────────────────────────────────────────────────────────

    def find_table(self, topic: str, geo_level: str) -> str:
        """Return the most relevant CBS table ID for a topic and geography level.

        Falls back to DEFAULT_TABLE if nothing matches.
        """
        topic_lower = topic.lower()

        # Priority tables first
        for tid in _PRIORITY_TABLES:
            if any(t.id == tid for t in self._tables):
                return tid  # always try priority tables; they cover most kerncijfers

        # Fuzzy title match
        scored: list[tuple[float, str]] = []
        for t in self._tables:
            score = _title_score(t.short_title.lower(), topic_lower)
            if score > 0:
                scored.append((score, t.id))

        if scored:
            scored.sort(reverse=True)
            return scored[0][1]

        return settings.DEFAULT_TABLE

    def get_measure_hint(self, topic: str, table_id: str) -> str | None:
        """Return a likely measure code for a topic keyword."""
        topic_lower = topic.lower()
        for kw, codes in _TOPIC_HINTS.items():
            if kw in topic_lower:
                # Find which codes actually exist in this table
                available = {m["code"] for m in self._measures.get(table_id, [])}
                for code in codes:
                    if not available or code in available:
                        return code
        return None

    def get_measures(self, table_id: str) -> list[dict[str, str]]:
        """Return measure metadata for a table (may be empty if not pre-fetched)."""
        return self._measures.get(table_id, [])

    def list_tables(self) -> list[TableMeta]:
        return self._tables

    def measures_summary(self, table_id: str, max_items: int = 30) -> str:
        """Return a compact text summary of measures for the LLM prompt."""
        measures = self._measures.get(table_id, [])[:max_items]
        if not measures:
            return "(measure list not available)"
        lines = [f"  {m['code']}: {m['title']} [{m.get('unit', '')}]" for m in measures]
        return "\n".join(lines)

    def tables_summary(self, max_items: int = 10) -> str:
        """Return a compact text summary of available tables for the LLM prompt."""
        rows = self._tables[:max_items]
        lines = [f"  {t.id}: {t.short_title} ({t.period})" for t in rows]
        return "\n".join(lines)


# ── Private helpers ───────────────────────────────────────────────────────────

async def _fetch_geo_tables() -> list[TableMeta]:
    """Fetch CBS OData Catalog and filter for geo-statistical tables."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(settings.CBS_CATALOG_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("Could not fetch CBS catalog: %s", exc)
        return _fallback_tables()

    tables: list[TableMeta] = []
    geo_keywords = re.compile(
        r"wijk|buurt|gemeente|kerncijfer|regionaal|regio|gebieden", re.IGNORECASE
    )
    for entry in data.get("value", []):
        title: str = entry.get("ShortTitle", entry.get("Title", ""))
        if not geo_keywords.search(title):
            continue
        tables.append(
            TableMeta(
                id=entry.get("Identifier", ""),
                title=entry.get("Title", ""),
                short_title=title,
                period=entry.get("Period", ""),
                geo_levels=_infer_geo_levels(title),
            )
        )

    if not tables:
        return _fallback_tables()

    # Ensure priority tables are always included
    existing_ids = {t.id for t in tables}
    for tid in _PRIORITY_TABLES:
        if tid not in existing_ids:
            tables.insert(0, TableMeta(id=tid, title=tid, short_title=tid, period="2024"))

    return tables


def _infer_geo_levels(title: str) -> list[str]:
    levels: list[str] = []
    t = title.lower()
    if "gemeente" in t:
        levels.append("gemeente")
    if "wijk" in t:
        levels.append("wijk")
    if "buurt" in t:
        levels.append("buurt")
    return levels or ["gemeente", "wijk", "buurt"]


def _title_score(title: str, query: str) -> float:
    words = query.split()
    return sum(1.0 for w in words if w in title) / max(len(words), 1)


def _fallback_tables() -> list[TableMeta]:
    return [
        TableMeta(
            id="86165NED",
            title="Kerncijfers wijken en buurten 2025",
            short_title="Kerncijfers wijken en buurten 2025",
            period="2025",
            geo_levels=["gemeente", "wijk", "buurt"],
        ),
        TableMeta(
            id="85984NED",
            title="Kerncijfers wijken en buurten 2024",
            short_title="Kerncijfers wijken en buurten 2024",
            period="2024",
            geo_levels=["gemeente", "wijk", "buurt"],
        ),
    ]
