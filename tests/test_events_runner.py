import pytest
from datetime import date
from events.runner import run
from events.base import EventSourceError, RawHeadline
from tests.conftest import FakeSupabase

@pytest.mark.asyncio
async def test_runner_dedupe_and_isolation(monkeypatch):
    class FakePIB:
        def __init__(self, mode=None): pass
        async def fetch_headlines(self, since):
            return [RawHeadline(source_url="http://pib1", headline="Export ban", published_date=date(2026, 9, 1), raw_text="Export ban")]
            
    class FakeNews:
        def __init__(self, mode=None): pass
        async def fetch_headlines(self, since):
            raise EventSourceError("Fail!")
            
    class FakeState:
        def __init__(self, mode=None): pass
        async def fetch_headlines(self, since):
            return [RawHeadline(source_url="http://state1", headline="Flood", published_date=date(2026, 9, 1), raw_text="Flood")]
            
    monkeypatch.setattr("events.runner.PIBSource", FakePIB)
    monkeypatch.setattr("events.runner.NewsFeedSource", FakeNews)
    monkeypatch.setattr("events.runner.StateBulletinsSource", FakeState)
    
    # Force Mock Extractor via config
    from app.config import get_settings
    settings = get_settings()
    settings.event_llm = "off"
    
    db = FakeSupabase()
    # Stub the in_ method for dedupe
    class FakeQuery:
        def select(self, *args): return self
        def in_(self, col, vals): return self
        def execute(self): 
            return type('Obj', (object,), {'data': []})()
    
    monkeypatch.setattr(db, "table", lambda t: FakeQuery() if t == "events" or t == "commodities" else FakeQuery())
    
    # We also need to capture inserts to events
    inserts = []
    class EventsTable(FakeQuery):
        def insert(self, row):
            inserts.append(row)
            return self
            
    monkeypatch.setattr(db, "table", lambda t: EventsTable() if t == "events" else FakeQuery())

    result = await run(db, since_days=2)
    assert result["seen"] == 2
    assert "news" in result["failed_sources"]
    assert result["new_written"] == 2
    assert result["extractor"] == "mock"
    assert len(inserts) == 2
