"""Tests for planner.py — LLM intent parsing.

Uses a mocked OpenAI client so no real API calls are made.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import MapPlan
from planner import _extract_json, generate_plan


# ── JSON extraction ───────────────────────────────────────────────────────────

def test_extract_json_plain():
    text = '{"intent": "map_choropleth", "table_id": "86165NED"}'
    result = _extract_json(text)
    assert result["intent"] == "map_choropleth"


def test_extract_json_with_markdown_fences():
    text = """
Here is your plan:
```json
{"intent": "map_choropleth", "table_id": "86165NED"}
```
"""
    result = _extract_json(text)
    assert result["table_id"] == "86165NED"


def test_extract_json_embedded_in_text():
    text = 'Sure! {"intent": "map_choropleth", "table_id": "86165NED", "measure_code": "Bevolking_1"} Done.'
    result = _extract_json(text)
    assert result["measure_code"] == "Bevolking_1"


def test_extract_json_raises_on_no_json():
    with pytest.raises(ValueError, match="No JSON"):
        _extract_json("There is no JSON here at all.")


# ── generate_plan ─────────────────────────────────────────────────────────────

def _make_valid_plan_dict(**overrides) -> dict:
    base = {
        "intent": "map_choropleth",
        "table_id": "86165NED",
        "measure_code": "Bevolking_1",
        "geography_level": "gemeente",
        "region_scope": None,
        "period": None,
        "classification": "quantile",
        "n_classes": 5,
        "message": "Showing population by gemeente.",
    }
    return {**base, **overrides}


def _make_mock_catalog():
    catalog = MagicMock()
    catalog.tables_summary.return_value = "  86165NED: Kerncijfers wijken en buurten 2025 (2025)"
    catalog.measures_summary.return_value = "  Bevolking_1: Bevolking [aantal]"
    return catalog


def _make_llm_response(content: str):
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.mark.asyncio
async def test_generate_plan_gemeente_population():
    catalog = _make_mock_catalog()
    plan_dict = _make_valid_plan_dict(geography_level="gemeente", region_scope=None)
    response = _make_llm_response(json.dumps(plan_dict))

    with patch("planner.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        plan = await generate_plan("Toon bevolking per gemeente", [], catalog)

    assert isinstance(plan, MapPlan)
    assert plan.geography_level == "gemeente"
    assert plan.measure_code == "Bevolking_1"


@pytest.mark.asyncio
async def test_generate_plan_amsterdam_wijken():
    catalog = _make_mock_catalog()
    plan_dict = _make_valid_plan_dict(
        geography_level="wijk",
        region_scope="GM0363",
        message="Showing districts in Amsterdam.",
    )
    response = _make_llm_response(json.dumps(plan_dict))

    with patch("planner.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        plan = await generate_plan("Zoom into Amsterdam wijken", [], catalog)

    assert plan.geography_level == "wijk"
    assert plan.region_scope == "GM0363"


@pytest.mark.asyncio
async def test_generate_plan_retries_on_invalid_json():
    """First LLM call returns garbage; second returns valid JSON."""
    catalog = _make_mock_catalog()
    plan_dict = _make_valid_plan_dict()
    valid_response = _make_llm_response(json.dumps(plan_dict))
    invalid_response = _make_llm_response("Sorry, I can't help with that.")

    call_count = 0

    async def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return invalid_response
        return valid_response

    with patch("planner.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = side_effect

        plan = await generate_plan("Show data", [], catalog)

    assert call_count == 2
    assert isinstance(plan, MapPlan)


@pytest.mark.asyncio
async def test_generate_plan_raises_after_two_failures():
    """Both LLM attempts return invalid JSON → ValueError raised."""
    catalog = _make_mock_catalog()
    bad_response = _make_llm_response("not json at all")

    with patch("planner.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=bad_response)

        with pytest.raises(ValueError, match="Could not generate a valid plan"):
            await generate_plan("Show data", [], catalog)


@pytest.mark.asyncio
async def test_generate_plan_uses_history():
    """History is included in the messages sent to the LLM."""
    catalog = _make_mock_catalog()
    plan_dict = _make_valid_plan_dict()
    response = _make_llm_response(json.dumps(plan_dict))

    captured_messages: list[dict] = []

    async def capture(**kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        return response

    with patch("planner.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = capture

        history = [
            {"role": "user", "content": "Show population"},
            {"role": "assistant", "content": "Here is the map."},
        ]
        await generate_plan("Now show by wijk", history, catalog)

    roles = [m["role"] for m in captured_messages]
    assert "system" in roles
    assert roles.count("user") >= 2   # history user + current user
