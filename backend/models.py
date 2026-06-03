"""Pydantic request/response models shared across the application."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Plan ─────────────────────────────────────────────────────────────────────

class MapPlan(BaseModel):
    """Structured execution plan produced by the LLM planner.

    The LLM fills this; backend services execute it.
    """

    intent: Literal["map_choropleth", "zoom", "compare", "info", "explain"] = "map_choropleth"
    table_id: str = Field(..., description="CBS table ID, e.g. '86165NED'")
    measure_code: str = Field(..., description="CBS column name, e.g. 'AantalInwoners_5'")
    geography_level: Literal["gemeente", "wijk", "buurt"]
    region_scope: str | None = Field(
        None,
        description="CBS region code to scope results, e.g. 'GM0363'. None = all Netherlands.",
    )
    province_scope: str | None = Field(
        None,
        description="Dutch province name, e.g. 'Noord-Holland'. Filters geometry to that province.",
    )
    buffer_scope: str | None = Field(
        None,
        description="Center region name or code for spatial buffer comparison (e.g. 'Gellicum').",
    )
    buffer_km: float = Field(15.0, ge=1.0, le=100.0, description="Buffer radius in km.")
    period: str | None = Field(
        None,
        description="Ignored — kerncijfers tables are single-year snapshots.",
    )
    classification: Literal["quantile", "equal", "jenks"] = "quantile"
    n_classes: int = Field(5, ge=3, le=9)
    message: str = Field(..., description="Short user-facing explanation in Dutch or English.")

    # ── Field validators ─────────────────────────────────────────────────────

    # ── Measures that have CBS data at wijk AND buurt level ──────────────────
    # Everything else is gemeente-only (energy, income, proximity, social security).
    _WIJK_BUURT_MEASURES: frozenset[str] = frozenset({
        # Demographics
        "AantalInwoners_5", "Bevolkingsdichtheid_34",
        "Mannen_6", "Vrouwen_7", "k_0Tot15Jaar_8", "k_65JaarOfOuder_12",
        "HuishoudensTotaal_29", "GeboorteTotaal_25", "SterfteTotaal_27",
        # Housing & WOZ
        "GemiddeldeWOZWaardeVanWoningen_39", "Woningvoorraad_35",
        "Koopwoningen_47", "HuurwoningenTotaal_48",
        # Vehicles
        "PersonenautoSTotaal_104", "PersonenautoSPerHuishouden_107",
        # Business
        "BedrijfsvestigingenTotaal_95",
        # Area / density
        "OppervlakteTotaal_115", "Omgevingsadressendichtheid_121",
        # Education (students/pupils)
        "LeerlingenPo_62", "StudentenHbo_65", "StudentenWo_66",
        # Care
        "JongerenMetJeugdzorgInNatura_91", "WmoClienten_93",
    })

    @field_validator("geography_level", mode="before")
    @classmethod
    def normalize_geography_level(cls, v: str) -> str:
        """Normalise synonyms; wijk/buurt pass through — model_validator enforces whitelist."""
        _synonyms: dict[str, str] = {
            "municipality": "gemeente", "municipalities": "gemeente",
            "gemeenten": "gemeente", "gemeentes": "gemeente",
            "wijk": "wijk", "wijken": "wijk", "district": "wijk", "districts": "wijk",
            "buurt": "buurt", "buurten": "buurt",
            "neighbourhood": "buurt", "neighborhoods": "buurt",
            "neighbourhoods": "buurt", "neighborhood": "buurt",
        }
        return _synonyms.get(str(v).strip().lower(), str(v).strip().lower())

    @model_validator(mode="after")
    def clamp_geography_to_whitelist(self) -> "MapPlan":
        """Downgrade wijk/buurt → gemeente when the measure has no sub-gemeente CBS data."""
        if self.geography_level in ("wijk", "buurt"):
            if self.measure_code not in self._WIJK_BUURT_MEASURES:
                self.geography_level = "gemeente"
        return self

    @field_validator("measure_code", mode="before")
    @classmethod
    def sanitize_measure_code(cls, v: str) -> str:
        """Normalise measure codes: map English synonyms → Dutch CBS names, then
        strip whitespace and reject codes containing spaces, slashes or operators.

        The LLM occasionally outputs English names or formulas like 'A_1 / B_2'.
        We take only the first valid token (word chars + underscore).
        """
        # English → Dutch CBS column name synonyms (LLM tends to invent these)
        _EN_TO_NL: dict[str, str] = {
            "NumberInhabitants_5":      "AantalInwoners_5",
            "Inhabitants_5":            "AantalInwoners_5",
            "Population_5":             "AantalInwoners_5",
            "TotalPopulation_5":        "AantalInwoners_5",
            "PopulationDensity_34":     "Bevolkingsdichtheid_34",
            "PopulationDensity_33":     "Bevolkingsdichtheid_34",
            "AreaTotal_115":            "OppervlakteTotaal_115",
            "TotalArea_115":            "OppervlakteTotaal_115",
            "WOZValue_39":              "GemiddeldeWOZWaardeVanWoningen_39",
            "HouseValue_39":            "GemiddeldeWOZWaardeVanWoningen_39",
            "AverageHouseValue_39":     "GemiddeldeWOZWaardeVanWoningen_39",
            "AverageIncome_78":         "GemiddeldInkomenPerInwoner_78",
            "Income_78":                "GemiddeldInkomenPerInwoner_78",
            "AverageIncomePerInhabitant_78": "GemiddeldInkomenPerInwoner_78",
            "GasConsumption_55":        "GemiddeldAardgasverbruik_55",
            "AverageGasConsumption_55": "GemiddeldAardgasverbruik_55",
            "ElectricityDelivery_53":   "GemiddeldeElektriciteitslevering_53",
            "DistanceSupermarket_111":  "AfstandTotGroteSupermarkt_111",
            "DistanceGP_110":           "AfstandTotHuisartsenpraktijk_110",
            "DistanceSchool_113":       "AfstandTotSchool_113",
            "Poverty_81":               "PersonenInArmoede_81",
            "PovertyRate_81":           "PersonenInArmoede_81",
            "Businesses_95":            "BedrijfsvestigingenTotaal_95",
        }
        v = str(v).strip()
        if v in _EN_TO_NL:
            return _EN_TO_NL[v]
        # Extract the first valid CBS column token: word chars and underscores only
        match = re.match(r"^([A-Za-z_]\w*)", v)
        if match:
            return match.group(1)
        raise ValueError(
            f"measure_code '{v}' is not a valid CBS column name. "
            "Use an exact key from DataProperties (e.g. 'AantalInwoners_5')."
        )

    @field_validator("table_id", mode="before")
    @classmethod
    def sanitize_table_id(cls, v: str) -> str:
        """Accept only alphanumeric CBS table IDs."""
        v = str(v).strip()
        if not re.match(r"^[A-Za-z0-9]+$", v):
            raise ValueError(f"table_id '{v}' is not a valid CBS table identifier.")
        return v

    @field_validator("message", mode="before")
    @classmethod
    def require_message(cls, v: str) -> str:
        """Reject empty messages — app.py will generate a fallback if needed."""
        return str(v).strip()   # keep even if empty; app.py fills it in

    @field_validator("region_scope", mode="before")
    @classmethod
    def sanitize_region_scope(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = str(v).strip()
        if v.lower() in ("null", "none", ""):
            return None
        # Must start with GM / WK / BU followed by digits
        if not re.match(r"^(GM|WK|BU)\d+$", v, re.IGNORECASE):
            return None   # silently drop invalid scope rather than crash
        return v.upper()

    @field_validator("buffer_scope", mode="before")
    @classmethod
    def sanitize_buffer_scope(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = str(v).strip()
        if v.lower() in ("null", "none", ""):
            return None
        return v

    # ── Cross-field validators ────────────────────────────────────────────────

    @model_validator(mode="after")
    def validate_scope_level(self) -> "MapPlan":
        """Ensure scoping fields are mutually consistent.

        Rules
        -----
        1. buffer_scope + region_scope: buffer takes precedence — region_scope
           must be None so the geometry fetch is not scoped to just one region.
        2. buurt region_scope on buurt map: doesn't make sense; widen to NL.
        """
        # Rule 1: buffer queries should never be scoped to a single region
        if self.buffer_scope and self.region_scope:
            self.region_scope = None

        # Rule 2: buurt code as region_scope on a buurt-level map is a no-op
        if self.region_scope and self.region_scope.startswith("BU"):
            self.region_scope = None

        return self


# ── API Requests ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list)


class PlanRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: list[dict[str, str]] = Field(default_factory=list)


class MapDataRequest(BaseModel):
    plan: MapPlan


# ── API Responses ─────────────────────────────────────────────────────────────

class ChatResponse(BaseModel):
    message: str
    plan: MapPlan
    geojson: dict[str, Any]          # GeoJSON FeatureCollection
    warnings: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)  # Related follow-up queries


class MapDataResponse(BaseModel):
    geojson: dict[str, Any]
    message: str
    warnings: list[str] = Field(default_factory=list)


class CatalogEntry(BaseModel):
    id: str
    title: str
    period: str
    geo_levels: list[str]


class CatalogResponse(BaseModel):
    tables: list[CatalogEntry]


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
