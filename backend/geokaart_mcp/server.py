"""GeoKaart MCP Server.

Exposes all GeoKaart data tools via the Model Context Protocol.
Mounted at /mcp on the main FastAPI app (streamable-HTTP transport).

Any MCP-compatible client can connect:
  - Claude Desktop  → add to claude_desktop_config.json
  - Cursor / VS Code → point at http://localhost:8000/mcp
  - GeoKaart orchestrator → internal tool calls
  - curl / mcp-client CLI → for debugging

Tool namespaces
---------------
  cbs_*   CBS StatLine — statistics, catalog, neighbors, region info
  pdok_*  PDOK — boundaries, geocoding, reverse geocoding

Usage (standalone, for testing)
--------------------------------
  cd backend
  uvicorn geokaart_mcp.server:asgi_app --port 8001 --reload

Usage (integrated — automatic via app.py mount)
-----------------------------------------------
  The main FastAPI app mounts this at /mcp via:
      app.mount("/mcp", mcp_asgi_app)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure backend root is on path when run standalone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from fastmcp import FastMCP

from geokaart_mcp.tools.cbs_tools import mcp as _cbs_mcp
from geokaart_mcp.tools.pdok_tools import mcp as _pdok_mcp

logger = logging.getLogger(__name__)

# ── Compose a single server from the sub-servers ──────────────────────────────

mcp = FastMCP(
    "GeoKaart",
    instructions=(
        "GeoKaart provides geospatial intelligence tools for the Netherlands. "
        "Use cbs_* tools to fetch regional statistics from CBS StatLine. "
        "Use pdok_* tools to fetch boundaries, geocode places, and reverse-geocode coordinates. "
        "All data comes from Dutch open government sources (CBS, PDOK). No API key required."
    ),
)

mcp.mount(_cbs_mcp, namespace="cbs")
mcp.mount(_pdok_mcp, namespace="pdok")

# ── ASGI app (streamable-HTTP transport, mountable on FastAPI) ─────────────────
# FastMCP 3.x returns a Starlette app from .http_app()
asgi_app = mcp.http_app(transport="streamable-http")
