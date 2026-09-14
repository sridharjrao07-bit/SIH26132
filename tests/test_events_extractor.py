import pytest
from datetime import date
from events.base import RawHeadline
from events.extractor import MockEventExtractor, LLMEventExtractor

@pytest.fixture
def mock_extractor():
    return MockEventExtractor()

@pytest.mark.asyncio
async def test_mock_extractor_export_ban(mock_extractor):
    headline = RawHeadline(
        source_url="http://test",
        headline="Export ban on onion (red)",
        published_date=date(2026, 9, 1),
        raw_text="Government bans export of onion (red)."
    )
    events = await mock_extractor.extract(headline)
    assert len(events) == 1
    assert events[0].commodity_name == "Onion (Red)"
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
        raw_text="Maize crop destroyed due to flood."
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
        raw_text="Nothing much happened."
    )
    events = await mock_extractor.extract(headline)
    assert events == []

@pytest.mark.asyncio
async def test_llm_extractor_fake_transport(monkeypatch):
    class FakeResponse:
        text = '[{"event_type": "weather", "direction": "down", "magnitude": "major", "confidence": 0.9, "reasoning": "test"}]'

    class FakeModels:
        def generate_content(self, model, contents, config):
            return FakeResponse()

    class FakeClientAio:
        models = FakeModels()

    class FakeClient:
        aio = FakeClientAio()
        models = FakeModels()

    monkeypatch.setattr("google.genai.Client", lambda api_key: FakeClient())

    extractor = LLMEventExtractor("fake_key")
    
    headline = RawHeadline(
        source_url="http://test4",
        headline="Heavy rain",
        published_date=date(2026, 9, 1),
        raw_text="Raining a lot."
    )
    events = await extractor.extract(headline)
    assert len(events) == 1
    assert events[0].event_type == "weather"

@pytest.mark.asyncio
async def test_llm_extractor_retry_on_bad_json(monkeypatch):
    attempts = []
    class FakeResponse:
        @property
        def text(self):
            attempts.append(1)
            if len(attempts) == 1:
                return 'bad json'
            return '[{"event_type": "policy", "direction": "up", "magnitude": "minor", "confidence": 0.8, "reasoning": "test"}]'

    class FakeModels:
        def generate_content(self, model, contents, config):
            return FakeResponse()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("google.genai.Client", lambda api_key: FakeClient())

    extractor = LLMEventExtractor("fake_key")
    headline = RawHeadline(
        source_url="http://test5",
        headline="Test",
        published_date=date(2026, 9, 1),
        raw_text="Test"
    )
    events = await extractor.extract(headline)
    assert len(events) == 1
    assert len(attempts) == 2
    assert events[0].event_type == "policy"

@pytest.mark.asyncio
async def test_llm_extractor_two_bad_json_fails_gracefully(monkeypatch):
    class FakeResponse:
        text = 'bad json forever'

    class FakeModels:
        def generate_content(self, model, contents, config):
            return FakeResponse()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr("google.genai.Client", lambda api_key: FakeClient())

    extractor = LLMEventExtractor("fake_key")
    headline = RawHeadline(
        source_url="http://test6",
        headline="Test",
        published_date=date(2026, 9, 1),
        raw_text="Test"
    )
    events = await extractor.extract(headline)
    assert events == []
