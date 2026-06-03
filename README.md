---
title: GeoKaart
emoji: 🗺️
colorFrom: blue
colorTo: cyan
sdk: docker
pinned: false
license: agpl-3.0
---

<div align="center">

# GeoKaart

**Conversational geospatial intelligence for the Netherlands**

*Ask anything about any place. Get a map.*

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![React 18](https://img.shields.io/badge/React-18-61DAFB?logo=react)](https://react.dev)
[![MapLibre GL](https://img.shields.io/badge/MapLibre%20GL-5-396CB2)](https://maplibre.org)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.1-FFF000?logo=duckdb)](https://duckdb.org)

</div>

---

## What is this?

GeoKaart is a **multi-agent geospatial platform** built on Dutch open government data.
You type a natural-language question. A planner LLM converts it to a structured execution plan.
Specialist agents fetch data from the right source. A narrator LLM turns the data into a sentence.
The frontend renders the result as an interactive MapLibre choropleth — live, on the same map you're looking at.

No dashboards. No prebuilt filters. No clicking through menus. Just ask.

```
"What is the average income per municipality in Noord-Holland?"
"Show energy consumption by neighbourhood in Rotterdam."
"Compare house values within 15km of Utrecht."
"Which municipalities have the highest elderly population share?"
```

---

## Data sources

GeoKaart is built exclusively on **open Dutch government APIs** — no proprietary data, no vendor lock-in.

| Source | Domain | API | Status |
|---|---|---|---|
| **CBS StatLine** | Regional statistics — demographics, housing, income, energy, health, labour | OData v3 | ✅ Live |
| **PDOK OGC** | Administrative boundaries — gemeente, wijk, buurt GeoJSON | OGC API Features | ✅ Live |
| **BAG / Kadaster** | Buildings, addresses, construction year, function type | REST | 🔧 Planned |
| **Rijkswaterstaat** | Road network (NWB), water levels, flood zones, traffic counts | WFS / REST | 🔧 Planned |
| **RIVM** | Air quality (NSL monitoring), environmental contamination, health atlas | WMS / REST | 🔧 Planned |
| **TNO / EP-online** | Energy labels, building energy performance, subsurface data | REST | 🔧 Planned |

### Why these six?

- **CBS StatLine** — 150+ years of Dutch statistics. OData API with gemeente/wijk/buurt granularity. The analytical backbone.
- **PDOK** — The authoritative geometry layer. Boundaries, geocoding, cadastral data. Everything spatial in the Netherlands routes through PDOK.
- **BAG** — Every building and address in the Netherlands. Enables distance queries, proximity analysis, building age maps.
- **Rijkswaterstaat** — Road network topology for routing. Flood risk zones, water body boundaries, live sensor data from 800+ monitoring stations.
- **RIVM** — Air quality index by location, chronic disease prevalence by region, soil contamination maps. Needed for environmental queries.
- **TNO / EP-online** — Energy label coverage for ~8M dwellings. Pairs with CBS energy data to identify efficiency gaps at neighbourhood scale.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser                                                         │
│  React 18 + Vite + MapLibre GL + Zustand                        │
│                                                                  │
│  ChatPanel ──── MapPanel ──── DataTable ──── [HITLCard*]         │
│       │              │                                           │
│   Zustand        MapLibre layers                                 │
│   chatStore      choropleth / route* / isochrone* / BAG*         │
└──────────────────────────┬───────────────────────────────────────┘
                           │  HTTP + SSE*
┌──────────────────────────▼───────────────────────────────────────┐
│  FastAPI  (Python 3.12)                                          │
│                                                                  │
│  POST /chat          ← main endpoint (live)                      │
│  POST /agent*        ← streaming SSE via AG-UI protocol          │
│  GET  /mcp*          ← MCP server mount                          │
│  POST /a2a*          ← FastA2A agent-to-agent handshake          │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│  Orchestrator  (Pydantic AI)                                     │
│                                                                  │
│  classifies intent → routes to specialist agent                  │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │ StatsAgent  │  │ SpatialAgent │  │ RoutingAgent            │ │
│  │ CBS StatLine│  │ BAG + PDOK   │  │ Rijkswaterstaat NWB     │ │
│  │ DuckDB cache│  │ proximity    │  │ ORS isochrones          │ │
│  └─────────────┘  └──────────────┘  └─────────────────────────┘ │
│  ┌─────────────┐  ┌──────────────┐                               │
│  │ EnvAgent    │  │ TimeAgent    │                               │
│  │ RIVM + TNO  │  │ CBS timeseries│                              │
│  │ air / energy│  │ trends       │                               │
│  └─────────────┘  └──────────────┘                               │
└──────────────────────────┬───────────────────────────────────────┘
                           │  MCP tool calls
┌──────────────────────────▼───────────────────────────────────────┐
│  MCP Tool Registry                                               │
│                                                                  │
│  cbs/get_stats          pdok/get_boundaries                      │
│  cbs/get_timeseries     pdok/geocode                             │
│  bag/nearest_facility   rws/get_road_network                     │
│  bag/within_radius      rivm/get_air_quality                     │
│  routing/get_route      tno/get_energy_labels                    │
│  routing/get_isochrone  fusion/isochrone_stats                   │
└──────────────────────────────────────────────────────────────────┘

* planned — see roadmap
```

---

## Agent skill inventory

GeoKaart is decomposed into **specialist agents**, each owning a data domain.
Agents communicate via [FastA2A](https://github.com/google-a2a/a2a-python) and expose their capabilities as [MCP tools](https://modelcontextprotocol.io).

### StatsAgent — CBS StatLine
| Skill | Description | Input | Output |
|---|---|---|---|
| `get_stats` | Fetch a single measure for a region | region code, measure, year? | `{value, label, unit}` |
| `compare_regions` | Rank regions by a measure | measure, scope, n | ranked list |
| `get_timeseries` | Multi-year trend for a measure | region, measure, year_from, year_to | `[{year, value}]` |
| `compute_trend` | Linear slope + acceleration | region, measure | `{slope, r2, direction}` |
| `find_outliers` | Regions deviating from median | measure, threshold | list of regions |
| `search_catalog` | Discover available measures | topic keyword | list of `{table_id, measure_code}` |

### SpatialAgent — BAG + PDOK
| Skill | Description | Input | Output |
|---|---|---|---|
| `get_boundaries` | Fetch gemeente/wijk/buurt GeoJSON | level, scope? | GeoJSON FeatureCollection |
| `geocode` | Address or place name → coordinates | query string | `{lat, lon, statcode}` |
| `nearest_facility` | Find closest N facilities of a type | point, type, n | list of BAG objects with distances |
| `within_radius` | All objects within X km | point, radius_km, type? | GeoJSON FeatureCollection |
| `get_neighbours` | Regions sharing a border | region code | list of region codes |
| `building_info` | Details on a specific building | address or point | `{bouwjaar, function, area, label}` |

### RoutingAgent — Rijkswaterstaat NWB + OpenRouteService
| Skill | Description | Input | Output |
|---|---|---|---|
| `get_route` | Directions A → B | origin, destination, mode | GeoJSON LineString + duration/distance |
| `get_isochrone` | Reachability polygon from a point | point, minutes, mode | GeoJSON Polygon |
| `isochrone_stats` | Stats inside a reachability polygon | point, minutes, mode, measure | choropleth GeoJSON + CBS data |
| `road_network` | NWB road segments in a bbox | bbox | GeoJSON LineString collection |
| `flood_risk` | RWS flood zone overlay | region or point | GeoJSON + risk classification |

### EnvAgent — RIVM + TNO
| Skill | Description | Input | Output |
|---|---|---|---|
| `get_air_quality` | NSL monitoring station data | region or point, pollutant? | `{NO2, PM10, PM25, O3}` |
| `get_energy_labels` | EP-online label distribution | region | `{A++: n, A+: n, …}` |
| `contamination_risk` | RIVM soil contamination flag | point or region | risk level + source |
| `health_indicators` | Chronic disease prevalence | region | `{diabetes_pct, cvd_pct, …}` |

### TimeAgent — CBS Multi-year
| Skill | Description | Input | Output |
|---|---|---|---|
| `get_timeseries` | Multi-year CBS data | region, measure, year_from, year_to | `[{year, value}]` |
| `forecast` | Linear/ARIMA projection | region, measure, ahead | `[{year, value, ci}]` |
| `compare_over_time` | Multiple regions on same measure | regions[], measure, years | multi-series `[{region, data[]}]` |
| `detect_anomaly` | Flag unusual year-over-year changes | measure, threshold | list of `{region, year, delta}` |

---

## Agentic protocols

### MCP (Model Context Protocol)
All skills are exposed as MCP tools. Any MCP-compatible client (Claude Desktop, Cursor, custom agent) can call GeoKaart's data layer directly.

```bash
# Mount the MCP server
uvicorn backend.mcp.server:app --port 8001
```

### FastA2A (Agent-to-Agent)
Agents communicate using the [A2A protocol](https://google.github.io/A2A). The orchestrator publishes an Agent Card at `/.well-known/agent.json` describing its skills. Downstream agents (routing, environment) register as sub-agents and receive tasks via A2A task delegation.

```json
// GET /.well-known/agent.json
{
  "name": "GeoKaart Orchestrator",
  "skills": ["stats", "spatial", "routing", "environment", "timeseries"],
  "endpoints": {
    "a2a": "/a2a",
    "mcp": "/mcp"
  }
}
```

### AG-UI (Agent-User Interaction)
Complex multi-step queries stream progress to the frontend via Server-Sent Events using the [AG-UI protocol](https://github.com/ag-ui-protocol/ag-ui). The frontend renders live tool-call status, intermediate map updates, and Human-in-the-Loop approval cards before executing irreversible or expensive actions.

```
Agent thinking…      → THINKING event   → spinner in chat
Agent fetching CBS…  → TOOL_CALL event  → progress chip
Agent rendering map… → DATA_READY event → map updates live
Agent: confirm?      → HITL_REQUEST     → approval card shown
User: ✓ Confirm      → HITL_RESPONSE    → agent proceeds
```

---

## Fusion queries

The real power is **cross-source queries** — no single API can answer these:

```
"What is the average income of people who can reach Amsterdam Centraal by bike in 20 minutes?"
→ RoutingAgent: isochrone(Amsterdam Centraal, 20min, bike)
→ StatsAgent:   get_stats(regions inside isochrone, income)
→ Narrator:     joins and renders choropleth

"Which neighbourhoods within 5km of the A10 have above-average NO2 and below-average income?"
→ RoutingAgent:  road_network(A10 bbox)
→ SpatialAgent:  within_radius(A10 centroid, 5km)
→ EnvAgent:      get_air_quality(filtered regions)
→ StatsAgent:    get_stats(filtered regions, income)
→ Narrator:      dual-measure choropleth

"Show energy label distribution in municipalities where gas consumption is declining fastest."
→ TimeAgent:     compute_trend(all municipalities, gas_consumption)
→ EnvAgent:      get_energy_labels(fastest-declining municipalities)
→ Narrator:      ranked bar chart + choropleth
```

---

## Quick start

### Docker (zero config)
```bash
git clone https://github.com/athithyai/GeoKaart.git
cd GeoKaart
cp .env.example .env
# Set your LLM provider in .env (Ollama works out of the box — no API key)
docker compose up
```
Open [http://localhost:7860](http://localhost:7860)

### Local dev
```bash
# Backend
pip install -r requirements.txt
cd backend && uvicorn app:app --reload --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

### LLM configuration
GeoKaart works with any OpenAI-compatible provider:

```env
# Free — local, no API key
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3.2
LLM_API_KEY=ollama

# Fast — Groq free tier
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.3-70b-versatile
LLM_API_KEY=gsk_...

# Best accuracy
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-...
```

---

## Project layout

```
GeoKaart/
├── backend/
│   ├── app.py                  FastAPI app — HTTP endpoints
│   ├── planner.py              Dual-LLM pipeline: planner + narrator
│   ├── models.py               MapPlan and API Pydantic models
│   ├── cbs_client.py           CBS StatLine OData v3 async client
│   ├── duckdb_client.py        Local DuckDB cache (cijfers.duckdb + cbs_spatial.duckdb)
│   ├── spatial_service.py      PDOK OGC boundary fetcher + disk cache
│   ├── join_engine.py          Stats ↔ geometry join + Jenks/quantile classification
│   ├── catalog_index.py        CBS table/measure discovery + semantic search
│   ├── ingest.py               Bulk CBS ingestion pipeline (background task)
│   │
│   ├── agents/                 [planned] Pydantic AI specialist agents
│   │   ├── orchestrator.py     Intent classification + agent routing
│   │   ├── stats_agent.py      StatsAgent — CBS/DuckDB tools
│   │   ├── spatial_agent.py    SpatialAgent — BAG + PDOK tools
│   │   ├── routing_agent.py    RoutingAgent — RWS NWB + ORS tools
│   │   ├── env_agent.py        EnvAgent — RIVM + TNO tools
│   │   └── time_agent.py       TimeAgent — CBS timeseries tools
│   │
│   ├── mcp/                    [planned] MCP server
│   │   ├── server.py           FastMCP mount
│   │   └── tools/              One file per data source
│   │
│   └── a2a/                    [planned] FastA2A agent cards + handlers
│
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── chat/           ChatPanel, MessageBubble, PlanCard, InputBar
│       │   ├── map/            MapPanel, MapLegend, MapControls, DataTable
│       │   └── layout/         AppShell, ThemeToggle
│       ├── store/              Zustand — chatStore, [agentStore planned]
│       └── types/              Shared TypeScript interfaces
│
└── docker-compose.yml
```

---

## Roadmap

| Phase | Capability | Status |
|---|---|---|
| 1 | CBS choropleth maps (gemeente/wijk/buurt) | ✅ Done |
| 2 | PDOK boundaries + buffer comparison | ✅ Done |
| 3 | MCP server — expose all tools | 🔧 Next |
| 4 | Pydantic AI orchestrator + StatsAgent | 🔧 Next |
| 5 | CBS timeseries + trend charts | ⏳ Planned |
| 6 | BAG client + proximity queries | ⏳ Planned |
| 7 | RWS routing + ORS isochrones | ⏳ Planned |
| 8 | Isochrone → CBS stats fusion | ⏳ Planned |
| 9 | RIVM air quality + TNO energy labels | ⏳ Planned |
| 10 | AG-UI event streaming + HITL cards | ⏳ Planned |
| 11 | FastA2A agent-to-agent protocol | ⏳ Planned |

---

## Contributing

GeoKaart is open-source and built for extension. Each data source is a self-contained agent module.
To add a new Dutch open data source: implement the MCP tools interface, register the agent with the orchestrator.

Issues, PRs, and new data source suggestions welcome.

---

## License & attribution

**Code:** AGPL-3.0 — see [LICENSE](LICENSE)

**Data:**
- [CBS StatLine](https://opendata.cbs.nl) — CC BY 4.0
- [PDOK](https://pdok.nl) — CC BY 4.0
- [BAG / Kadaster](https://www.kadaster.nl/zakelijk/producten/adressen-en-gebouwen/bag-2.0-extract) — CC BY 4.0
- [Rijkswaterstaat Open Data](https://www.rijkswaterstaat.nl/zakelijk/open-data) — CC BY 4.0
- [RIVM](https://www.rivm.nl/documenten/rivm-open-data-licentie) — CC BY 4.0
- [TNO / EP-online](https://www.ep-online.nl) — CC BY 4.0
