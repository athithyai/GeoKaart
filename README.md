---
title: GeoKaart
emoji: 🗺️
colorFrom: blue
colorTo: cyan
sdk: docker
pinned: false
license: agpl-3.0
---

# GeoKaart

**Conversational geospatial intelligence for the Netherlands.**

Ask anything about any place in the Netherlands — statistics, routing, proximity, timeseries — and get an interactive map as the answer.

---

## What it does

Type a question in plain Dutch or English. GeoKaart classifies your intent, fetches data from open Dutch sources, and renders the result on a live MapLibre map.

**Examples:**
- *"Bevolkingsdichtheid per gemeente in Noord-Holland"*
- *"WOZ-waarde in Amsterdam per buurt"*
- *"Vergelijk inkomen in gemeenten rondom Utrecht"*
- *"Welke gemeenten hebben het hoogste gasverbruik?"*
- *"Toon huishoudens per wijk in Rotterdam"*

---

## Capabilities

| Capability | Description |
|---|---|
| **Choropleth maps** | 45+ statistical measures at gemeente / wijk / buurt level |
| **Region drill-down** | Click any region to scope the map and follow-up queries |
| **Buffer comparison** | Compare a region against its neighbours within X km |
| **Province filter** | Scope any query to a single province |
| **Multi-layer** | Switch between gemeente / wijk / buurt without losing context |
| **Timeseries** *(coming)* | Year-over-year trends for any measure |
| **Proximity / BAG** *(coming)* | Nearest facility, within-radius queries |
| **Routing / isochrones** *(coming)* | Reachability polygons + stat fusion |

---

## Data sources

All data sources are **open Dutch government data** — no proprietary APIs, no registration required for core features.

| Source | What it provides | URL |
|---|---|---|
| **CBS StatLine** | Regional statistics (demographics, housing, income, energy, …) | [opendata.cbs.nl](https://opendata.cbs.nl) |
| **PDOK OGC API** | Administrative boundaries (gemeente / wijk / buurt GeoJSON) | [api.pdok.nl](https://api.pdok.nl) |
| **BAG Kadaster** *(coming)* | Buildings, addresses, construction year, function type | [bag.basisregistraties.overheid.nl](https://bag.basisregistraties.overheid.nl) |
| **OpenRouteService** *(coming)* | Routing, isochrones (free tier) | [openrouteservice.org](https://openrouteservice.org) |

---

## Tech stack

**Backend:** Python 3.12 · FastAPI · DuckDB · Pydantic AI *(planned)* · MCP *(planned)*

**Frontend:** React 18 · TypeScript · Vite · MapLibre GL · Zustand

**LLM:** OpenAI-compatible — works with GPT-4o, Groq (llama-3.3-70b), or Ollama (local, free)

---

## Quick start

### Docker (recommended)

```bash
git clone https://github.com/athithyai/GeoKaart.git
cd GeoKaart
cp .env.example .env
# Edit .env — set your LLM provider (Ollama works out of the box, no key needed)
docker compose up
```

Open [http://localhost:7860](http://localhost:7860).

### Local dev

```bash
# Backend
cd backend
pip install -r ../requirements.txt
uvicorn app:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

---

## Configuration

Copy `.env.example` to `.env` and configure:

```env
# LLM — pick one provider

# Ollama (free, local, default)
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3.2
LLM_API_KEY=ollama

# Groq (fast cloud, free tier)
# LLM_BASE_URL=https://api.groq.com/openai/v1
# LLM_MODEL=llama-3.3-70b-versatile
# LLM_API_KEY=gsk_...

# OpenAI (best accuracy)
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_MODEL=gpt-4o
# LLM_API_KEY=sk-...
```

---

## Architecture

```
Frontend (React + MapLibre)
        │
        ▼
FastAPI backend
   /chat  ──→  Planner (LLM) ──→ MapPlan
                                      │
              ┌───────────────────────┼────────────────────┐
              ▼                       ▼                    ▼
         CBS StatLine             PDOK OGC            (planned)
         duckdb_client          spatial_service    routing / BAG
              │                       │
              └──────── join_engine ──┘
                              │
                        GeoJSON response
```

---

## Project structure

```
GeoKaart/
├── backend/
│   ├── app.py              FastAPI application
│   ├── planner.py          Dual-LLM pipeline (planner + narrator)
│   ├── models.py           Pydantic models (MapPlan, ChatRequest/Response)
│   ├── cbs_client.py       CBS StatLine OData v3 client
│   ├── duckdb_client.py    Local DuckDB cache layer
│   ├── spatial_service.py  PDOK boundary fetcher
│   ├── join_engine.py      Stats ↔ geometry join + choropleth classification
│   ├── catalog_index.py    CBS table/measure discovery
│   └── ingest.py           Bulk CBS data ingestion pipeline
├── frontend/
│   └── src/
│       ├── components/     React UI (chat, map, controls, legend)
│       ├── store/          Zustand state (chat, map)
│       └── types/          Shared TypeScript types
└── docker-compose.yml
```

---

## License

AGPL-3.0 — see [LICENSE](LICENSE).

Data attribution: [CBS StatLine](https://opendata.cbs.nl) · [PDOK](https://pdok.nl) — CC BY 4.0
