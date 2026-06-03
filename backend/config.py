"""Application configuration via pydantic-settings.

Switch LLM providers by changing two env vars:
  - GPT-4o  : LLM_BASE_URL=https://api.openai.com/v1   LLM_MODEL=gpt-4o
  - Groq    : LLM_BASE_URL=https://api.groq.com/openai/v1  LLM_MODEL=llama-3.3-70b-versatile
  - Ollama  : LLM_BASE_URL=http://localhost:11434/v1   LLM_MODEL=llama3.2
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM (OpenAI-compatible — defaults to Ollama local) ──────────────────
    LLM_BASE_URL: str = "http://localhost:11434/v1"   # Ollama default
    LLM_MODEL: str = "llama3.2"                       # any `ollama pull <model>`
    LLM_API_KEY: str = "ollama"                       # Ollama ignores this value

    # ── Data APIs ────────────────────────────────────────────────────────────
    CBS_ODATA_BASE: str = "https://opendata.cbs.nl/ODataFeed/odata"
    CBS_CATALOG_URL: str = "https://opendata.cbs.nl/ODataCatalog/Tables?$format=json"
    PDOK_OGC_BASE: str = "https://api.pdok.nl/cbs/gebiedsindelingen/ogc/v1"

    # ── Cache TTLs (seconds) ─────────────────────────────────────────────────
    CACHE_TTL_METADATA: int = 3600        # 1 h  — CBS catalog & DataProperties
    CACHE_TTL_GEOMETRY: int = 86400       # 24 h — PDOK geometries
    CACHE_TTL_DATA: int = 900             # 15 m — CBS observations

    # ── Defaults ─────────────────────────────────────────────────────────────
    DEFAULT_TABLE: str = "86165NED"
    DEFAULT_GEO_YEAR: int = 2024

    # ── Server ───────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
