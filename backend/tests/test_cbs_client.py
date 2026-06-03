"""Tests for cbs_client.py — CBS OData HTTP client."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from cbs_client import (
    _build_region_filter,
    get_latest_period,
    get_observations,
)


# ── Region filter tests ───────────────────────────────────────────────────────

def test_build_region_filter_gemeente_national():
    f = _build_region_filter("gemeente", None)
    assert f == "startswith(RegioS,'GM')"


def test_build_region_filter_wijk_national():
    f = _build_region_filter("wijk", None)
    assert f == "startswith(RegioS,'WK')"


def test_build_region_filter_wijk_scoped_to_gemeente():
    f = _build_region_filter("wijk", "GM0363")
    assert "WK0363" in f


def test_build_region_filter_buurt_scoped_to_gemeente():
    f = _build_region_filter("buurt", "GM0599")
    assert "BU0599" in f


def test_build_region_filter_gemeente_specific():
    f = _build_region_filter("gemeente", "GM0363")
    assert "GM0363" in f


# ── Latest period detection ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_latest_period_returns_most_recent():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "value": [
            {"Perioden": "2023JJ00"},
            {"Perioden": "2025JJ00"},
            {"Perioden": "2024JJ00"},
        ]
    }

    with patch("cbs_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.return_value = mock_response

        result = await get_latest_period("86165NED", mock_client)

    assert result == "2025JJ00"


# ── get_observations ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_observations_returns_dataframe():
    """When period is supplied explicitly, no period-detection call is made.
    The first (and only) mock call is for the TypedDataSet observations."""
    rows = [
        {"RegioS": "GM0363   ", "Perioden": "2024JJ00", "Bevolking_1": 921000.0},
        {"RegioS": "GM0599   ", "Perioden": "2024JJ00", "Bevolking_1": 651000.0},
    ]

    obs_response = MagicMock()
    obs_response.raise_for_status = MagicMock()
    obs_response.json.return_value = {"value": rows}

    with patch("cbs_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=obs_response)

        df = await get_observations(
            table_id="86165NED",
            measure_code="Bevolking_1",
            geography_level="gemeente",
            region_scope=None,
            period="2024JJ00",  # explicit → no period-detection call
        )

    assert isinstance(df, pd.DataFrame)
    assert "RegioS" in df.columns
    assert "Bevolking_1" in df.columns
    # Verify CBS padding spaces are stripped
    assert df["RegioS"].str.contains(r"^\s").sum() == 0


@pytest.mark.asyncio
async def test_get_observations_pagination():
    """Two pages of results are concatenated correctly.
    Period is passed explicitly so call 1 = page1, call 2 = page2."""
    page1 = [{"RegioS": f"GM{i:04d}", "Perioden": "2024JJ00", "Bevolking_1": float(i)}
             for i in range(10_000)]
    page2 = [{"RegioS": f"GM{i:04d}", "Perioden": "2024JJ00", "Bevolking_1": float(i)}
             for i in range(10_000, 10_100)]

    call_n = 0

    async def mock_get(url, params=None, **kwargs):
        nonlocal call_n
        call_n += 1
        r = MagicMock()
        r.raise_for_status = MagicMock()
        if call_n == 1:
            r.json.return_value = {"value": page1}   # first page
        else:
            r.json.return_value = {"value": page2}   # second (last) page
        return r

    with patch("cbs_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.side_effect = mock_get

        # Use a different table_id to avoid cache collision with the previous test
        df = await get_observations("85984NED", "Bevolking_1", "gemeente", None, "2024JJ00")

    assert len(df) == 10_100


@pytest.mark.asyncio
async def test_get_observations_404_raises_value_error():
    import httpx as _httpx

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 404
        raise _httpx.HTTPStatusError("Not found", request=MagicMock(), response=resp)

    with patch("cbs_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.side_effect = mock_get

        with pytest.raises(ValueError, match="not found"):
            await get_observations("BADTABLE", "Bevolking_1", "gemeente", None, "2024JJ00")
