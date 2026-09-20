from datetime import date

import pytest
from events.base import RawHeadline
from events.extractor import LLMEventExtractor, MockEventExtractor


@pytest.fixture
def mock_extractor():
    return MockEventExtractor()


@pytest.mark.asyncio
async def test_mock_extractor_export_ban(mock_extractor):
    headline = RawHeadline(
        source_url="http://test",
        headline="Export ban on onion (red)",
        published_date=date(2026, 9, 1),
        raw_text="Government bans export of onion (red).",
    )
    events = await mock_extractor.extract(headline)
    assert len(events) == 1
    assert events[0].commodity_name == "Onion"
    assert events[0].event_type == "policy"
    assert events[0].direction == "down"
    assert events[0].magnitude == "moderate"
    assert events[0].confidence == 0.8


@pytest.mark.asyncio
async def test_mock_extractor_flood(mock_extractor):
    headline = RawHeadline(
        source_url="http://test2",
        headline="Flood in maize fields",
        published_date=date(2026, 9, 1),
        raw_text="Maize crop destroyed due to flood.",
    )
    events = await mock_extractor.extract(headline)
    assert len(events) == 1
    assert events[0].commodity_name == "Maize"
    assert events[0].event_type == "weather"
    assert events[0].direction == "down"
    assert events[0].magnitude == "major"


@pytest.mark.asyncio
async def test_mock_extractor_no_match(mock_extractor):
    headline = RawHeadline(
        source_url="http://test3",
        headline="Normal day in market",
        published_date=date(2026, 9, 1),
        raw_text="Nothing much happened.",
    )
    events = await mock_extractor.extract(headline)
    assert events == []


import httpx
import respx


@pytest.mark.asyncio
@respx.mock
async def test_llm_extractor_fake_transport():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '[{"event_type": "weather", "direction": "down", "magnitude": "major", "confidence": 0.9, "reasoning": "test"}]'
                        }
                    }
                ]
            },
        )
    )

    extractor = LLMEventExtractor("fake_key")

    headline = RawHeadline(
        source_url="http://test4",
        headline="Heavy rain",
        published_date=date(2026, 9, 1),
        raw_text="Raining a lot.",
    )
    events = await extractor.extract(headline)
    assert len(events) == 1
    assert events[0].event_type == "weather"


@pytest.mark.asyncio
@respx.mock
async def test_llm_extractor_retry_on_bad_json():
    attempts = []

    def side_effect(request):
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "bad json"}}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '[{"event_type": "policy", "direction": "up", "magnitude": "minor", "confidence": 0.8, "reasoning": "test"}]'
                        }
                    }
                ]
            },
        )

    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=side_effect)

    extractor = LLMEventExtractor("fake_key")
    headline = RawHeadline(
        source_url="http://test5", headline="Test", published_date=date(2026, 9, 1), raw_text="Test"
    )
    events = await extractor.extract(headline)
    assert len(events) == 1
    assert len(attempts) == 2
    assert events[0].event_type == "policy"


@pytest.mark.asyncio
@respx.mock
async def test_llm_extractor_two_bad_json_fails_gracefully():
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "bad json forever"}}]}
        )
    )

    extractor = LLMEventExtractor("fake_key")
    headline = RawHeadline(
        source_url="http://test6", headline="Test", published_date=date(2026, 9, 1), raw_text="Test"
    )
    events = await extractor.extract(headline)
    assert events == []
