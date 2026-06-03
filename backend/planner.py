"""LLM-powered intent planner.

Responsibilities
----------------
- Accept natural-language user messages
- Build a context-rich system prompt using the CBS catalog
- Call an OpenAI-compatible LLM (GPT-4o or Ollama)
- Extract and validate the JSON plan
- Retry once if the plan fails Pydantic validation
- NEVER execute queries, fetch data, or render anything

The planner is purely declarative — it produces a MapPlan; all execution
happens in the backend services.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from catalog_index import CatalogIndex, _PRIORITY_TABLES
from config import get_settings
from models import MapPlan

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Gemeente name → code lookup (most-requested cities) ──────────────────────
_GEMEENTE_CODES: dict[str, str] = {
    "amsterdam": "GM0363",
    "rotterdam": "GM0599",
    "den haag": "GM0518",
    "the hague": "GM0518",
    "utrecht": "GM0344",
    "eindhoven": "GM0772",
    "groningen": "GM0014",
    "tilburg": "GM0855",
    "almere": "GM0034",
    "breda": "GM0758",
    "nijmegen": "GM0268",
    "enschede": "GM0153",
    "haarlem": "GM0392",
    "arnhem": "GM0202",
    "zaanstad": "GM0479",
    "amersfoort": "GM0307",
    "apeldoorn": "GM0200",
    "s-hertogenbosch": "GM0796",
    "den bosch": "GM0796",
    "zwolle": "GM0193",
    "leiden": "GM0546",
    "maastricht": "GM0935",
    "dordrecht": "GM0505",
    "zoetermeer": "GM0637",
    "deventer": "GM0150",
    "delft": "GM0503",
    "alkmaar": "GM0361",
    "leeuwarden": "GM0080",
    "venlo": "GM0983",
    "emmen": "GM0114",
}

# ── System prompt template ────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a spatial data query planner for GeoKaart, a Dutch geospatial intelligence platform.
Your ONLY job is to convert the user's natural-language question into a structured JSON plan.
You must NOT execute queries, fetch data, or explain how to code anything.

=== APPROVED CBS TABLES (use ONLY these) ===
{tables_summary}

⚠️  CRITICAL: You MUST use one of the table IDs listed above. Do NOT invent or guess table IDs.
    When in doubt, use "{default_table}" — it is the most comprehensive kerncijfers table.

=== MEASURE CODES FOR {default_table} (kerncijfers wijken en buurten) ===
{measures_summary}

=== GEOGRAPHY LEVEL ===
- gemeente   → whole municipalities (GM#### codes)          — always available
- wijk       → neighbourhoods within a municipality         — only for whitelisted measures
- buurt      → sub-neighbourhood level                      — only for whitelisted measures

WHITELIST — use wijk or buurt ONLY for these measures:
  Demographics : AantalInwoners_5, Bevolkingsdichtheid_34, Mannen_6, Vrouwen_7,
                 k_0Tot15Jaar_8, k_65JaarOfOuder_12, HuishoudensTotaal_29
  Housing/WOZ  : GemiddeldeWOZWaardeVanWoningen_39, Woningvoorraad_35,
                 Koopwoningen_47, HuurwoningenTotaal_48
  Vehicles     : PersonenautoSTotaal_104, PersonenautoSPerHuishouden_107
  Business     : BedrijfsvestigingenTotaal_95
  Area/density : OppervlakteTotaal_115, Omgevingsadressendichtheid_121
  Education    : LeerlingenPo_62, StudentenHbo_65, StudentenWo_66
  Care         : JongerenMetJeugdzorgInNatura_91, WmoClienten_93

For ALL other measures (energy, income, proximity, social security) → use gemeente only.
When geography_level is wijk or buurt, region_scope MUST be a GM#### code (the parent municipality).
⚠️  NEVER use province_scope with wijk or buurt — it has no effect. Use region_scope instead.
    "auto's per wijk in Utrecht" → geography_level: "wijk", region_scope: "GM0344" (NOT province_scope)

=== WELL-KNOWN GEMEENTE CODES ===
{gemeente_codes}

=== OUTPUT FORMAT ===
Output ONLY a single valid JSON object — no markdown, no code fences, no commentary.

{{
  "intent": "map_choropleth",
  "table_id": "<one of the approved table IDs above>",
  "measure_code": "<exact column name from the measure codes list above>",
  "geography_level": "<gemeente | wijk | buurt — use wijk/buurt only for whitelisted measures above>",
  "region_scope": null,
  "province_scope": null,
  "buffer_scope": null,
  "buffer_km": 15,
  "period": null,
  "classification": "quantile",
  "n_classes": 5,
  "message": "<short user-facing explanation in the same language as the user>"
}}

=== KEYWORD → MEASURE CODE CHEAT SHEET ===
CRITICAL LANGUAGE RULE: measure_code values are Dutch CBS column names.
They start with Dutch words: Aantal, Gemiddeld, Bevolking, Woningvoorraad, k_, Personen, etc.
NEVER invent English codes like "NumberInhabitants_5", "PopulationDensity_34", "AverageIncome_78",
"AreaTotal_115", "HouseValue_39". If you don't find the exact code, use the cheat sheet below.

IMPORTANT: Use the EXACT table_id and measure_code shown. Do NOT guess or invent codes.

CBS table coverage:
  86165NED = 2025: demographics, housing, vehicles, area
  85984NED = 2024: ALL categories (use for energy, labor, income, social, care, business, proximity)

── BEVOLKING (Population) ──────────────────────────────────────────────────────
  table_id: "86165NED"
  population / bevolking / inwoners          → AantalInwoners_5
  population density / bevolkingsdichtheid / dichtheid / inhabitants per km²
                                             → Bevolkingsdichtheid_34   ← USE THIS for density
  men / mannen                               → Mannen_6
  women / vrouwen                            → Vrouwen_7
  age 0-15 / kinderen / jongeren             → k_0Tot15Jaar_8
  elderly / ouderen / 65+                    → k_65JaarOfOuder_12
  births / geboorte  [use 85984NED!]         → GeboorteTotaal_25
  deaths / sterfte   [use 85984NED!]         → SterfteTotaal_27
  households / huishoudens [use 85984NED!]   → HuishoudensTotaal_29

── WONEN EN VASTGOED (Housing) ──────────────────────────────────────────────────
  table_id: "86165NED"  (or 85984NED — both work)
  house value / WOZ / huiswaarde             → GemiddeldeWOZWaardeVanWoningen_39
  housing stock / woningvoorraad             → Woningvoorraad_35
  owner-occupied / koopwoning %              → Koopwoningen_47
  rental / huurwoning %                      → HuurwoningenTotaal_48

── ENERGIE (Energy) ─────────────────────────────────────────────────────────────
  table_id: "85984NED"   ← REQUIRED for energy (not in 2025 table)
  electricity / elektriciteit / stroomverbruik   → GemiddeldeElektriciteitslevering_53
  gas / gasverbruik / aardgas                    → GemiddeldAardgasverbruik_55
  ⚠ solar / zonnestroom → NOT AVAILABLE (CBS does not publish at regional level)

CRITICAL: Any measure marked with ⚠ as NOT AVAILABLE MUST use intent="info" with a message
explaining the limitation. Do NOT use map_choropleth with a fallback measure code.

── ONDERWIJS (Education) ────────────────────────────────────────────────────────
  table_id: "85984NED"   ← REQUIRED for education (not in 2025 table)
  primary school / basisschool leerlingen    → LeerlingenPo_62
  students hbo / hogeschool                 → StudentenHbo_65
  students wo / universiteit                → StudentenWo_66
  ⚠ education level % (HboWo_69) → NOT AVAILABLE (null in CBS regional data)

── ARBEID (Labor / Employment) ──────────────────────────────────────────────────
  ⚠ ARBEID IS NOT AVAILABLE: CBS does NOT publish labor participation, employment rate,
    or self-employment at gemeente/wijk/buurt level. All values are null in CBS data.
  → For labor-related queries, use intent="info" and explain this limitation in message.
  → Do NOT use WerkzameBeroepsbevolking_70, Nettoarbeidsparticipatie_71, or PercentageZelfstandigen_75.

── INKOMEN (Income) ─────────────────────────────────────────────────────────────
  table_id: "85984NED"   ← REQUIRED for income (not in 2025 table)
  income / inkomen per inwoner / wealthy/arm → GemiddeldInkomenPerInwoner_78
  income per recipient / per ontvanger       → GemiddeldInkomenPerInkomensontvanger_77
  standardised income / gestandaardiseerd    → GemGestandaardiseerdInkomen_83
  median wealth / mediaan vermogen           → MediaanVermogenVanParticuliereHuish_86
  poverty / armoede                          → PersonenInArmoede_81

── SOCIALE ZEKERHEID (Social security / Benefits) ───────────────────────────────
  table_id: "85984NED"   ← REQUIRED for benefits (not in 2025 table)
  bijstand / welfare / social assistance     → PersonenPerSoortUitkeringBijstand_87
  disability / arbeidsongeschiktheid / AO    → PersonenPerSoortUitkeringAO_88
  unemployment benefit / WW                  → PersonenPerSoortUitkeringWW_89
  AOW / pension / pensioen                   → PersonenPerSoortUitkeringAOW_90

── ZORG (Care) ───────────────────────────────────────────────────────────────────
  table_id: "85984NED"   ← REQUIRED for care (not in 2025 table)
  youth care / jeugdzorg                     → JongerenMetJeugdzorgInNatura_91
  WMO / social support / maatwerk            → WmoClienten_93

── BEDRIJFSVESTIGINGEN (Business establishments) ────────────────────────────────
  table_id: "85984NED"   ← REQUIRED for businesses (not in 2025 table)
  businesses / bedrijven / vestigingen       → BedrijfsvestigingenTotaal_95

── MOTORVOERTUIGEN (Motor vehicles) ─────────────────────────────────────────────
  table_id: "86165NED"  (or 85984NED — both work)
  total cars / personenauto's / auto's       → PersonenautoSTotaal_104  (prefer this)
  cars per household / per huishouden        → PersonenautoSPerHuishouden_107

── NABIJHEID VAN VOORZIENINGEN (Proximity to facilities) ────────────────────────
  table_id: "85984NED"   ← REQUIRED for proximity (not in 2025 table)
  geography_level: "gemeente" always for these measures.
  distance to supermarket / supermarkt       → AfstandTotGroteSupermarkt_111
  distance to GP / huisarts / dokter         → AfstandTotHuisartsenpraktijk_110
  distance to school / basisschool           → AfstandTotSchool_113
  distance to daycare / kinderdagverblijf    → AfstandTotKinderdagverblijf_112

── OPPERVLAKTE (Surface area / urban density) ───────────────────────────────────
  table_id: "86165NED"  (or 85984NED — both work)
  surface area / oppervlakte / total area    → OppervlakteTotaal_115
  ⚠ OppervlakteTotaal_115 is AREA IN HECTARES — NOT population density!
    For density, use Bevolkingsdichtheid_34 (see BEVOLKING section above).
  address density / OAD / stedelijkheid      → Omgevingsadressendichtheid_121

=== PROVINCE SCOPING ===
When the user mentions a Dutch province (e.g. "in Noord-Holland", "per gemeente in Utrecht"),
set province_scope to the exact Dutch province name AND keep region_scope = null.
Supported province names (exact spelling):
  Groningen, Friesland, Drenthe, Overijssel, Flevoland, Gelderland,
  Utrecht, Noord-Holland, Zuid-Holland, Zeeland, Noord-Brabant, Limburg

Example: "Gasverbruik per gemeente in Noord-Holland"
→ geography_level: "gemeente", province_scope: "Noord-Holland", region_scope: null

=== BUFFER / SURROUNDING AREAS SCOPING ===
Use buffer_scope whenever the user wants to compare ONE named region against its neighbours.

Trigger phrases (Dutch and English):
  "compare X with other municipalities/gemeenten"
  "how does X compare"
  "X vs surrounding/nearby areas"
  "X en omgeving", "X eo"
  "vergelijk X met andere gemeenten"
  "vergelijk X met omliggende gemeenten"

Rule: set buffer_scope = EXACT gemeente name, region_scope = null, geography_level = "gemeente".
The backend finds all gemeenten within buffer_km of that center.
Always use buffer_km: 50 for gemeente comparisons.

Examples:
  "Compare IJsselstein with other municipalities"
  → geography_level: "gemeente", buffer_scope: "IJsselstein", buffer_km: 50, region_scope: null

  "Gasverbruik in Leiden en omgeving"
  → geography_level: "gemeente", buffer_scope: "Leiden", buffer_km: 50, region_scope: null

  "Vergelijk Amsterdam met omliggende gemeenten"
  → geography_level: "gemeente", buffer_scope: "Amsterdam", buffer_km: 50, region_scope: null

=== SELECTED REGION CONTEXT ===
When you see [Selected region: NAME (CODE)] appended to the user message,
the user recently clicked that region on the map. Use it as follows:

USE selected region CODE as region_scope ONLY when the user's message:
- Names or implies that specific region: "inkomen in NAME", "WOZ in NAME"
- Is a follow-up with NO place mentioned: "show gas consumption", "how many residents?"

IGNORE the selected region (region_scope = null) when the user's message:
- Contains "per municipality", "per gemeente", "all municipalities", "nationally", "heel Nederland"
- Mentions a DIFFERENT city, province, or region: "in Friesland", "in Noord-Holland", "in Amsterdam"
- Contains a Dutch province name → use province_scope instead, region_scope = null

Examples:
  "[Selected region: Land van Cuijk (GM1982)]\nInkomen in Land van Cuijk"
  → region_scope: "GM1982"

  "[Selected region: Land van Cuijk (GM1982)]\nGasverbruik per gemeente in Friesland"
  → region_scope: null, province_scope: "Friesland"   ← IGNORE selected region

  "[Selected region: Land van Cuijk (GM1982)]\nPopulation density per municipality"
  → region_scope: null   ← IGNORE selected region, this is a national map

KEY: "surrounding" / "omgeving" / "omliggend" → ALWAYS use buffer_scope, NEVER region_scope.

=== EXPLAIN INTENT ===
Use intent = "explain" when the user asks to INTERPRET or UNDERSTAND the current map —
not to load new data.
ALWAYS use intent = "explain" (NEVER "info") when the message is:
  "explain", "leg uit", "uitleggen", "verklaar", "wat betekent dit?", "what does this mean?",
  "why is X so high/low?", "is that a lot?", "which gemeente is richest/poorest?",
  "insights", "find me insights", "give me insights", "analyse", "analyze"
Keep all other plan fields identical to the current map context.

Template for explain intent:
{{
  "intent": "explain",
  "table_id": "{default_table}",
  "measure_code": "AantalInwoners_5",
  "geography_level": "gemeente",
  "region_scope": null,
  "province_scope": null,
  "buffer_scope": null,
  "buffer_km": 15,
  "period": null,
  "classification": "quantile",
  "n_classes": 5,
  "message": ""
}}

=== CONVERSATIONAL MESSAGES ===
IMPORTANT: Any message that names or implies a CBS measure (WOZ, inkomen, bevolking, inwoners,
supermarkt, gas, elektriciteit, armoede, bijstand, auto, woningen, etc.) MUST use
intent = "map_choropleth" — even if the message is short or conversational.
Only use intent = "info" when there is NO data topic at all (pure greetings, thanks, meta-questions
like "what can you show me?").

For "what can you do" / "help" / "what data do you have", use this exact message:
"I can show interactive maps of Dutch regional statistics, proximity queries, routes, and timeseries per gemeente.

Try asking me:
• Population density per gemeente in Noord-Holland
• Average WOZ house value per gemeente
• Compare income in Utrecht with surrounding municipalities
• Gas consumption per gemeente in Friesland

Data comes from CBS Kerncijfers — covering population, housing, income, energy, social benefits, care, businesses, and proximity to facilities."

For greetings (hi, hello, goedemorgen), respond warmly in the same language and invite a question.
For thanks / feedback, acknowledge it briefly and invite another question.

Template for info intent:
{{
  "intent": "info",
  "table_id": "{default_table}",
  "measure_code": "AantalInwoners_5",
  "geography_level": "gemeente",
  "region_scope": null,
  "province_scope": null,
  "buffer_scope": null,
  "buffer_km": 15,
  "period": null,
  "classification": "quantile",
  "n_classes": 5,
  "message": "<your response here>"
}}

=== RULES ===
1. table_id  MUST be one of the approved table IDs — never use any other.
2. measure_code MUST be one of the exact codes listed in the measure codes section above.
   Do NOT invent codes. Do NOT use title words as codes.
   Use the CHEAT SHEET above first; fall back to the full measure list if not listed.
3. period = null always — these tables are single-year snapshots with no time dimension.
4. region_scope controls MAP SCOPE:
   - Specific city mentioned  → region_scope = that city's GM code (shows ONLY that gemeente)
   - "per municipality" / "per gemeente" / no place mentioned → region_scope = null (all Netherlands)
   - Province mentioned + gemeente level → province_scope = province name, region_scope = null
   - Province mentioned + wijk/buurt level → IGNORE province, use region_scope = city GM code
   - Comparison / buffer queries → region_scope = null, use buffer_scope instead
   - [Selected region] in message: IGNORE it if user mentions any other place or says "per municipality"
5. Default to table_id = "{default_table}" unless another approved table is clearly better.
6. The message field is REQUIRED and must never be empty. Write 1-2 sentences describing
   what the map shows (measure, level, location). Use the same language as the user.
   Example: "Gemiddeld inkomen per inwoner per gemeente in Rotterdam."
7. Output ONLY the JSON object — nothing else.
8. geography_level for wijk/buurt queries:
   "Motorvoertuigen per buurt in Rotterdam"  → geography_level: "buurt",  region_scope: "GM0599"
   "WOZ per wijk in Amsterdam"               → geography_level: "wijk",   region_scope: "GM0363"
   "Bevolking per wijk in Utrecht"           → geography_level: "wijk",   region_scope: "GM0344"
   "Gasverbruik per buurt in Den Haag"       → geography_level: "gemeente", region_scope: "GM0518"  ← gas NOT whitelisted, use gemeente
   "Inkomen per buurt in Eindhoven"          → geography_level: "gemeente", region_scope: "GM0772"  ← income NOT whitelisted, use gemeente
"""


# ── Client factory ────────────────────────────────────────────────────────────

def _make_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
    )


# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict[str, Any]:
    """Extract and clean the first JSON object from LLM output.

    Handles common small-model quirks:
    - Markdown code fences (```json … ```)
    - JavaScript-style // line comments
    - Trailing commas before } or ]
    - Truncated output (LLM cut off mid-JSON) → auto-repair
    """
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = re.sub(r"```\s*$", "", text).strip()

    # Find the outermost JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        # LLM may have truncated mid-JSON: find `{` and try to repair
        open_idx = text.find("{")
        if open_idx == -1:
            raise ValueError(f"No JSON object found in LLM response:\n{text[:300]}")
        # Partial JSON — extract what we have and attempt to salvage intent/message
        partial = text[open_idx:]
        intent_m = re.search(r'"intent"\s*:\s*"(\w+)"', partial)
        message_m = re.search(r'"message"\s*:\s*"([^"]*)"', partial)
        # Return a safe info-intent fallback with whatever we could extract
        return {
            "intent": intent_m.group(1) if intent_m else "info",
            "table_id": "86165NED",
            "measure_code": "AantalInwoners_5",
            "geography_level": "gemeente",
            "region_scope": None,
            "period": None,
            "classification": "quantile",
            "n_classes": 5,
            "message": message_m.group(1) if message_m else "",
        }

    raw = match.group()

    # Remove // line comments
    raw = re.sub(r"//[^\n]*", "", raw)
    # Remove /* block comments */
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.DOTALL)
    # Remove trailing commas before } or ]
    raw = re.sub(r",\s*([}\]])", r"\1", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Last resort: try to at least extract intent + message via regex
        intent_m = re.search(r'"intent"\s*:\s*"(\w+)"', raw)
        message_m = re.search(r'"message"\s*:\s*"([^"]*)"', raw)
        if intent_m:
            return {
                "intent": intent_m.group(1),
                "table_id": "86165NED",
                "measure_code": "AantalInwoners_5",
                "geography_level": "gemeente",
                "region_scope": None,
                "period": None,
                "classification": "quantile",
                "n_classes": 5,
                "message": message_m.group(1) if message_m else "",
            }
        raise ValueError(
            f"Could not parse JSON from LLM response:\nCleaned text:\n{raw[:400]}"
        )


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_system_prompt(catalog: CatalogIndex, context: dict | None = None) -> str:
    gemeente_lines = "\n".join(
        f"  {name.title()}: {code}" for name, code in list(_GEMEENTE_CODES.items())[:20]
    )
    # Only show priority tables so the LLM cannot pick anything else
    priority_tables = [t for t in catalog.list_tables() if t.id in _PRIORITY_TABLES]
    tables_lines = "\n".join(
        f"  {t.id}: {t.short_title} ({t.period})" for t in priority_tables
    ) or f"  {settings.DEFAULT_TABLE}: Kerncijfers wijken en buurten (latest)"

    prompt = _SYSTEM_PROMPT.format(
        tables_summary=tables_lines,
        default_table=settings.DEFAULT_TABLE,
        measures_summary=catalog.measures_summary(settings.DEFAULT_TABLE, max_items=25),
        gemeente_codes=gemeente_lines,
    )

    if context:
        scope_str = context.get("region_scope") or "null (all Netherlands)"
        context_block = (
            "\n=== CURRENT MAP CONTEXT ===\n"
            "Carry over geography_level and region_scope ONLY if the user does not specify a new place.\n"
            "NEVER carry over measure_code — always derive measure_code fresh from the user's question\n"
            "using the KEYWORD → MEASURE CODE CHEAT SHEET above. The cheat sheet always takes priority.\n"
            f"  geography_level:  {context.get('geography_level', 'gemeente')}\n"
            f"  region_scope:     {scope_str}\n"
        )
        prompt = context_block + "\n" + prompt

    return prompt


# ── Measure-code whitelist (all codes in the cheat sheet) ────────────────────
# If the LLM picks a code not in this set (e.g. confuses supermarket distance
# with gas), the plan is rejected and retried with an explicit error message.

_VALID_MEASURE_CODES: frozenset[str] = frozenset({
    # Bevolking
    "AantalInwoners_5", "Bevolkingsdichtheid_34", "Mannen_6", "Vrouwen_7",
    "k_0Tot15Jaar_8", "k_65JaarOfOuder_12", "GeboorteTotaal_25",
    "SterfteTotaal_27", "HuishoudensTotaal_29",
    # Wonen
    "GemiddeldeWOZWaardeVanWoningen_39", "Woningvoorraad_35",
    "Koopwoningen_47", "HuurwoningenTotaal_48",
    # Energie
    "GemiddeldeElektriciteitslevering_53", "GemiddeldAardgasverbruik_55",
    # Onderwijs
    "LeerlingenPo_62", "StudentenHbo_65", "StudentenWo_66",
    # Inkomen
    "GemiddeldInkomenPerInwoner_78", "GemiddeldInkomenPerInkomensontvanger_77",
    "GemGestandaardiseerdInkomen_83", "MediaanVermogenVanParticuliereHuish_86",
    "PersonenInArmoede_81",
    # Sociale zekerheid
    "PersonenPerSoortUitkeringBijstand_87", "PersonenPerSoortUitkeringAO_88",
    "PersonenPerSoortUitkeringWW_89", "PersonenPerSoortUitkeringAOW_90",
    # Zorg
    "JongerenMetJeugdzorgInNatura_91", "WmoClienten_93",
    # Bedrijven
    "BedrijfsvestigingenTotaal_95",
    # Motorvoertuigen
    "PersonenautoSTotaal_104", "PersonenautoSPerHuishouden_107",
    # Nabijheid
    "AfstandTotGroteSupermarkt_111", "AfstandTotHuisartsenpraktijk_110",
    "AfstandTotSchool_113", "AfstandTotKinderdagverblijf_112",
    # Oppervlakte
    "OppervlakteTotaal_115", "Omgevingsadressendichtheid_121",
})


# ── Keyword → measure override (deterministic, bypasses LLM confusion) ───────
# Ordered list: first match wins. More specific patterns must come before generic ones.
# Only fires for map_choropleth intent; info/explain are left untouched.

_KEYWORD_OVERRIDES: list[tuple[list[str], str]] = [
    # Energie
    (["gasverbruik", "aardgas", " gas "],           "GemiddeldAardgasverbruik_55"),
    (["elektriciteitsverbruik", "elektriciteit",
      "stroomverbruik", "stroom"],                  "GemiddeldeElektriciteitslevering_53"),
    # Nabijheid — "afstand" is the key signal
    (["afstand tot school", "afstand school"],      "AfstandTotSchool_113"),
    (["afstand tot supermarkt", "afstand supermarkt",
      "supermarkt"],                                "AfstandTotGroteSupermarkt_111"),
    (["afstand tot huisarts", "afstand huisarts",
      "huisarts", "dokter"],                        "AfstandTotHuisartsenpraktijk_110"),
    (["afstand tot kinderdagverblijf",
      "kinderdagverblijf", "kinderopvang"],         "AfstandTotKinderdagverblijf_112"),
    # Wonen
    (["woz", "woningwaarde", "huiswaarde",
      "woningprijs"],                               "GemiddeldeWOZWaardeVanWoningen_39"),
    (["woningvoorraad"],                            "Woningvoorraad_35"),
    (["koopwoning", "koopwoningen"],                "Koopwoningen_47"),
    (["huurwoning", "huurwoningen"],                "HuurwoningenTotaal_48"),
    # Bevolking
    (["bevolkingsdichtheid", "dichtheid",
      "density"],                                   "Bevolkingsdichtheid_34"),
    (["inwoners", "bevolking", "population",
      "inhabitants"],                               "AantalInwoners_5"),
    (["kinderen", "jongeren", "0-15", "0 tot 15"],  "k_0Tot15Jaar_8"),
    (["ouderen", "65+", "senioren"],                "k_65JaarOfOuder_12"),
    (["huishoudens"],                               "HuishoudensTotaal_29"),
    # Inkomen
    (["armoede", "poverty"],                        "PersonenInArmoede_81"),
    (["vermogen", "wealth", "rijkdom"],             "MediaanVermogenVanParticuliereHuish_86"),
    (["inkomen", "income", "salaris"],              "GemiddeldInkomenPerInwoner_78"),
    # Sociale zekerheid
    (["bijstand", "welfare"],                       "PersonenPerSoortUitkeringBijstand_87"),
    (["arbeidsongeschiktheid", " ao "],             "PersonenPerSoortUitkeringAO_88"),
    ([" ww ", "werkloosheid", "unemployment"],      "PersonenPerSoortUitkeringWW_89"),
    (["aow", "pensioen", "pension"],                "PersonenPerSoortUitkeringAOW_90"),
    # Zorg
    (["jeugdzorg"],                                 "JongerenMetJeugdzorgInNatura_91"),
    (["wmo"],                                       "WmoClienten_93"),
    # Bedrijven
    (["bedrijven", "bedrijfsvestiging",
      "vestigingen", "businesses"],                 "BedrijfsvestigingenTotaal_95"),
    # Voertuigen
    (["personenauto", "auto's", "voertuig",
      "cars"],                                      "PersonenautoSTotaal_104"),
    # Onderwijs (after "afstand tot school" to avoid false match)
    (["leerlingen", "basisonderwijs"],              "LeerlingenPo_62"),
    (["hbo", "hogeschool"],                         "StudentenHbo_65"),
    (["universiteit", "wo "],                       "StudentenWo_66"),
    # Oppervlakte
    (["omgevingsadressendichtheid", "oad",
      "stedelijkheid"],                             "Omgevingsadressendichtheid_121"),
    (["oppervlakte"],                               "OppervlakteTotaal_115"),
]


def _apply_keyword_override(plan: "MapPlan", user_message: str) -> "MapPlan":
    """Correct measure_code using keyword matching when the LLM picks wrong.

    Small models (llama3.2 etc.) reliably get the wrong code on energy/proximity
    queries. This deterministic override acts as a safety net.
    Only fires for map_choropleth; leaves intent=info/explain untouched.
    """
    if plan.intent != "map_choropleth":
        return plan

    msg = f" {user_message.lower()} "  # pad so word-boundary patterns work
    for keywords, correct_code in _KEYWORD_OVERRIDES:
        if any(kw in msg for kw in keywords):
            if plan.measure_code != correct_code:
                logger.info(
                    "Keyword override: %r → %s (was %s)",
                    user_message[:60], correct_code, plan.measure_code,
                )
                return plan.model_copy(update={"measure_code": correct_code})
            break  # correct code already, stop checking
    return plan


# Whitelisted measure codes that have wijk/buurt CBS data (mirrors models.py)
_WIJK_BUURT_MEASURES: frozenset[str] = frozenset({
    "AantalInwoners_5", "Bevolkingsdichtheid_34", "Mannen_6", "Vrouwen_7",
    "k_0Tot15Jaar_8", "k_65JaarOfOuder_12", "HuishoudensTotaal_29",
    "GeboorteTotaal_25", "SterfteTotaal_27",
    "GemiddeldeWOZWaardeVanWoningen_39", "Woningvoorraad_35",
    "Koopwoningen_47", "HuurwoningenTotaal_48",
    "PersonenautoSTotaal_104", "PersonenautoSPerHuishouden_107",
    "BedrijfsvestigingenTotaal_95",
    "OppervlakteTotaal_115", "Omgevingsadressendichtheid_121",
    "LeerlingenPo_62", "StudentenHbo_65", "StudentenWo_66",
    "JongerenMetJeugdzorgInNatura_91", "WmoClienten_93",
})


def _apply_geography_override(plan: "MapPlan", user_message: str) -> "MapPlan":
    """Force geography_level to wijk or buurt when the user explicitly requests it
    and the current measure supports sub-gemeente data.

    phi4 and other small models reliably default to 'gemeente' even when the user
    says 'per buurt' or 'per wijk'. This deterministic post-parse fix mirrors
    _apply_keyword_override for measure codes.
    """
    if plan.intent != "map_choropleth":
        return plan

    msg = f" {user_message.lower()} "

    # Detect explicit sub-gemeente level request
    wants_buurt = any(kw in msg for kw in [
        " buurt", "per buurt", "buurtniveau", "buurtlevel",
        "neighbourhood", "neighborhoods", "neighbourhood level",
    ])
    wants_wijk = any(kw in msg for kw in [
        " wijk", "per wijk", "wijkniveau", "wijklevel",
        " district", "districts",
    ])

    if not (wants_buurt or wants_wijk):
        return plan  # user didn't ask for sub-gemeente level

    # Only upgrade if the measure is whitelisted
    if plan.measure_code not in _WIJK_BUURT_MEASURES:
        return plan  # measure has no buurt/wijk CBS data → leave at gemeente

    # buurt takes precedence if both keywords appear
    target_level = "buurt" if wants_buurt else "wijk"

    if plan.geography_level != target_level:
        logger.info(
            "Geography override: %r → geography_level '%s' (was '%s', measure='%s')",
            user_message[:60], target_level, plan.geography_level, plan.measure_code,
        )
        return plan.model_copy(update={"geography_level": target_level})

    return plan


# ── Main public API ───────────────────────────────────────────────────────────

async def generate_plan(
    message: str,
    history: list[dict[str, str]],
    catalog: CatalogIndex,
    context: dict | None = None,
    lang: str | None = None,
) -> MapPlan:
    """Parse a natural-language message into a validated MapPlan.

    Retries once if the LLM output fails validation.
    """
    client = _make_client()
    system_prompt = _build_system_prompt(catalog, context=context)

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

    # Include recent chat history (last 6 turns for context)
    for turn in history[-6:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({"role": "user", "content": message})

    for attempt in range(2):
        logger.info("LLM plan attempt %d for: %r", attempt + 1, message[:80])
        try:
            response = await client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=800,
                temperature=0.0,
            )
            raw_text = response.choices[0].message.content or ""
            logger.debug("LLM raw output: %s", raw_text[:500])

            plan_dict = _extract_json(raw_text)
            plan = MapPlan.model_validate(plan_dict)

            # Keyword override — fix small-model measure confusions deterministically
            plan = _apply_keyword_override(plan, message)

            # Geography override — force buurt/wijk when user explicitly asked for it
            plan = _apply_geography_override(plan, message)

            # Whitelist check — catch valid-but-wrong measure codes before CBS fetch
            if plan.intent == "map_choropleth" and plan.measure_code not in _VALID_MEASURE_CODES:
                raise ValueError(
                    f"INVALID measure_code '{plan.measure_code}'. "
                    f"You MUST use one of the exact codes from the KEYWORD → MEASURE CODE CHEAT SHEET. "
                    f"Valid examples: AantalInwoners_5, GemiddeldAardgasverbruik_55, "
                    f"GemiddeldeWOZWaardeVanWoningen_39, AfstandTotSchool_113."
                )

            return plan

        except Exception as exc:
            if attempt == 0:
                logger.warning("Plan attempt 1 failed (%s); retrying …", exc)
                # Inject the error into the conversation so the LLM can self-correct
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response was invalid: {exc}. "
                            "Please output ONLY a valid JSON object matching the schema."
                        ),
                    }
                )
            else:
                logger.error("Plan generation failed after 2 attempts: %s", exc)
                raise ValueError(f"Could not generate a valid plan: {exc}") from exc

    # Should never reach here
    raise RuntimeError("Unexpected planner state")


async def generate_narration(
    user_message: str,
    plan: "MapPlan",
    meta: dict | None,
    history: list[dict[str, str]],
    measure_label: str,
    top_regions: list[dict] | None = None,
    center_value: float | None = None,
    lang: str | None = None,
) -> str:
    """Generate a rich conversational reply after data has been fetched.

    This is a second LLM call — separate from the planner — with higher
    temperature for more natural language. Never raises: falls back to a
    template string on any failure.

    Parameters
    ----------
    user_message  : The original user question
    plan          : The executed MapPlan
    meta          : Join metadata (breaks, n_matched, n_total, period) or None
    history       : Recent chat history (last 4 turns used)
    measure_label : Human-readable measure name
    top_regions   : Top-N regions by value (for highlighting interesting points)
    """
    client = _make_client()

    # Measure descriptions (unit + context) for the narrator
    _MEASURE_UNITS: dict[str, str] = {
        "AfstandTotGroteSupermarkt_111":      "km (distance to nearest large supermarket)",
        "AfstandTotHuisartsenpraktijk_110":   "km (distance to nearest GP practice)",
        "AfstandTotSchool_113":               "km (distance to nearest primary school)",
        "AfstandTotKinderdagverblijf_112":    "km (distance to nearest daycare centre)",
        "GemiddeldeWOZWaardeVanWoningen_39":  "× €1,000 (average WOZ property value)",
        "GemiddeldInkomenPerInwoner_78":      "× €1,000 (average income per resident)",
        "GemiddeldInkomenPerInkomensontvanger_77": "× €1,000 (average income per recipient)",
        "GemGestandaardiseerdInkomen_83":     "× €1,000 (standardised income)",
        "MediaanVermogenVanParticuliereHuish_86": "× €1,000 (median household wealth)",
        "GemiddeldAardgasverbruik_55":        "m³ (average natural gas consumption)",
        "GemiddeldeElektriciteitslevering_53":"kWh (average electricity delivery)",
        "AantalInwoners_5":                   "residents (total population count)",
        "Bevolkingsdichtheid_34":             "residents per km² (population density)",
        "PersonenInArmoede_81":               "% (percentage of residents in poverty)",
        "PersonenPerSoortUitkeringBijstand_87": "% (welfare benefit recipients)",
        "PersonenPerSoortUitkeringWW_89":     "% (unemployment benefit recipients)",
        "Koopwoningen_47":                    "% (owner-occupied housing share)",
        "Woningvoorraad_35":                  "units (total housing stock)",
        "BedrijfsvestigingenTotaal_95":       "establishments (total business count)",
    }
    measure_unit = _MEASURE_UNITS.get(plan.measure_code, "")

    # Resolve language: explicit UI preference > heuristic word-match
    if lang and lang.lower() in ("nl", "dutch"):
        lang = "Dutch"
    elif lang and lang.lower() in ("en", "english"):
        lang = "English"
    else:
        dutch_signals = {
            "nederland", "dutch", "nl", "gemeente", "wat", "toon",
            "laat", "gemiddeld", "per", "bereik", "vergelijk", "leg", "uit",
            "waarom", "welke", "hoeveel", "veel", "weinig", "hoog", "laag",
        }
        lang = "Dutch" if any(w in user_message.lower().split() for w in dutch_signals) else "English"

    # Build a compact data summary — kept under 200 tokens
    data_lines: list[str] = []
    if meta and meta.get("n_matched", 0) > 0:
        n_matched = meta["n_matched"]
        n_total   = meta.get("n_total", n_matched)
        breaks    = meta.get("breaks", [])
        period    = meta.get("period", "")

        def _fmt(v: float) -> str:
            if abs(v) >= 1_000_000: return f"{v / 1_000_000:.1f}M"
            if abs(v) >= 1_000: return f"{v:,.0f}"
            if v != int(v): return f"{v:.1f}"
            return str(int(v))

        if len(breaks) >= 2:
            lo, hi = breaks[0], breaks[-1]
            mid_idx = len(breaks) // 2
            approx_median = breaks[mid_idx]
            measure_full = f"{measure_label}" + (f" [{measure_unit}]" if measure_unit else "")
            data_lines.append(f"Measure: {measure_full}")
            data_lines.append(f"Level: {plan.geography_level}")
            if plan.buffer_scope:
                data_lines.append(
                    f"Scope: {plan.buffer_scope} and surroundings within {plan.buffer_km:.0f} km "
                    f"— refer to this specific area, NOT a single municipality and NOT all Netherlands"
                )
            elif plan.region_scope:
                # Resolve the GM code to a human name if available from top_regions
                region_display = plan.region_scope
                if top_regions:
                    region_display = top_regions[0].get("statnaam", plan.region_scope)
                data_lines.append(f"Scope: {region_display} (single municipality/region)")
            elif plan.province_scope:
                data_lines.append(f"Scope: {plan.province_scope} (province, multiple municipalities)")
            else:
                data_lines.append(f"Scope: all Netherlands — this is a NATIONAL map, do NOT say 'in je gemeente'")
            data_lines.append(f"Regions with data: {n_matched}/{n_total}")
            data_lines.append(f"Range: {_fmt(lo)} – {_fmt(hi)}")
            data_lines.append(f"Approx. median: {_fmt(approx_median)}")
            if period:
                data_lines.append(f"Reference period: {period}")
            if top_regions:
                # For buffer queries, exclude the center itself from the top-5
                # so the list shows purely surrounding regions
                display_regions = top_regions
                if plan.buffer_scope:
                    bs_lower = plan.buffer_scope.strip().lower()
                    display_regions = [
                        r for r in top_regions
                        if r.get("statnaam", "").lower() != bs_lower
                    ]
                region_str = ", ".join(
                    f"{r['statnaam']} ({_fmt(r['value'])})"
                    for r in display_regions[:5]
                    if r.get("value") is not None
                )
                if region_str:
                    label = "Highest surrounding values" if plan.buffer_scope else "Highest values"
                    data_lines.append(f"{label}: {region_str}")

            if center_value is not None and plan.buffer_scope:
                data_lines.append(
                    f"Center region ({plan.buffer_scope}) value: {_fmt(center_value)}"
                )
                data_lines.append(
                    "TASK: Start by stating the center region's value, then compare it to the "
                    "surrounding area using the median and range. Mention 1-2 specific surrounding "
                    "regions by name if interesting. Do NOT say the center ranks 'Xth place'."
                )

    data_summary = "\n".join(data_lines) if data_lines else "No data statistics available."

    if data_lines:
        is_buffer = bool(plan.buffer_scope)
        system = (
            f"You are GeoKaart, a Dutch geospatial intelligence assistant powered by open Dutch data (CBS StatLine, PDOK, BAG). "
            f"Respond in {lang}. "
            f"CRITICAL: The map displays '{measure_label}'. "
            f"Use EXACTLY this measure name in your response. "
            f"Do NOT use any other measure name or topic from the user's question. "
            + (
                f"Write 2–4 engaging sentences: first state the center region's value compared to the surrounding area, "
                f"then give an interesting observation. Be specific with numbers from DATA CONTEXT only. "
                f"Use words like 'opvallend', 'vergelijkbaar', 'beduidend hoger/lager', 'ligt op'. "
                if is_buffer
                else
                f"Write 2–3 sentences in a product voice — clear, data-driven, neutral. "
            )
            + f"Your response MUST be based ONLY on the DATA CONTEXT below. "
            f"Do NOT add facts, comparisons, or context not in the DATA CONTEXT. "
            f"Do NOT mention national averages or statistics from previous queries — "
            f"use ONLY the Range and Approx. median values provided here. "
            f"Do NOT mention AI, language models, or assistants. "
            f"Do NOT repeat the user's question. No bullet points or markdown. "
            f"IMPORTANT: Check the Scope line in DATA CONTEXT. "
            f"If Scope says 'all Netherlands', this is a national map — NEVER say 'in je gemeente' or single-region phrasing. "
            f"If Scope mentions 'surroundings within', compare the center to the surrounding area median. "
            f"If Scope is a single municipality/region, use municipality-specific language.\n\n"
            f"DATA CONTEXT:\n{data_summary}"
        )
    else:
        # No data: tell the LLM exactly what failed so it gives a specific,
        # helpful explanation rather than a generic fallback.
        no_data_context = (
            f"Measure requested: {measure_label} ({plan.measure_code})\n"
            f"Geography level: {plan.geography_level}\n"
            f"Scope: {plan.region_scope or 'all Netherlands'}\n"
            f"Table: {plan.table_id}"
        )
        system = (
            f"You are GeoKaart, a Dutch geospatial intelligence assistant. "
            f"Respond in {lang}. "
            f"The data request below returned NO results from CBS StatLine. "
            f"In 1–2 sentences: apologise briefly and explain specifically what was requested "
            f"and why it likely failed (e.g. CBS does not publish this measure at gemeente level, "
            f"or the table does not contain this column). "
            f"Suggest a concrete alternative if obvious (e.g. a different measure that is available). "
            f"Do NOT invent statistics or facts. "
            f"Do NOT give a generic description of the assistant. "
            f"Do NOT mention AI, language models, or assistants.\n\n"
            f"FAILED REQUEST:\n{no_data_context}"
        )

    msgs: list[dict[str, str]] = [{"role": "system", "content": system}]
    # Include only the last 4 turns — Narrator needs less context than Planner
    for turn in history[-4:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            msgs.append({"role": turn["role"], "content": turn["content"]})
    msgs.append({"role": "user", "content": user_message})

    try:
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=msgs,  # type: ignore[arg-type]
            max_tokens=300,
            temperature=0.7,
        )
        result = (response.choices[0].message.content or "").strip()
        if result:
            return result
    except Exception as exc:
        logger.warning("Narrator LLM call failed: %s", exc)

    # Graceful fallback — never crashes
    if data_lines:
        range_line = next((l for l in data_lines if l.startswith("Range:")), "")
        return f"{measure_label} per {plan.geography_level}. {range_line}".strip(" .")
    return f"{measure_label} per {plan.geography_level}."
